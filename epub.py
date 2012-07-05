# -*- coding: utf-8 -*-
#from django.utils.translation import ugettext_lazy as _
from copy import deepcopy
import hashlib

from lxml import etree
#TODO: use => from lxml.html.clean import clean_html
from zipfile import ZipFile
import logging, datetime, os, os.path, lxml, lxml.html
from urllib import unquote_plus
from xml.parsers.expat import ExpatError

import constants
from constants import ENC, BW_BOOK_CLASS, STYLESHEET_MIMETYPE, XHTML_MIMETYPE, DTBOOK_MIMETYPE
from constants import NAMESPACES as NS
from toc import NavPoint, TOC, InvalidEpubException

import toc as util


class EpubArchive(object):
    '''Represents an entire epub container'''

    _CONTAINER = constants.CONTAINER
    _parsed_metadata = None
    _parsed_toc = None

    def __init__(self, basename, use_spine_as_toc=True):
        self.name = basename
        self.title = None
        self.opf = None
        self.authors = None
        self.toc = None
        self.pages = []
        self.use_spine_as_toc = use_spine_as_toc
        self.explode()

    def safe_title(self):
        '''Return a URL-safe title'''
        return safe_name(self.title) or 'Untitled'

    def author(self):
        '''This method returns the author, if only one, or the first author in
        the list with ellipses for additional authors.'''

        if not self.authors:
            return ''
        elif len(self.authors) > 1:
          return self.authors[0] + '...'
        else:
          return self.authors[0]

    def get_subjects(self):
        return self._get_metadata(constants.DC_SUBJECT_TAG, self.opf, plural=True) or []

    def get_rights(self):
        return self._get_metadata(constants.DC_RIGHTS_TAG, self.opf, as_string=True) or ''

    def get_language(self):
        return self._get_metadata(constants.DC_LANGUAGE_TAG, self.opf, as_string=True) or ''

    def get_major_language(self):
        lang = self.get_language()
        if not lang:
            return None
        if '-' in lang or '_' in lang:
            for div in ('-', '_'):
                if div in lang:
                    return lang.split(div)[0]
        return lang

    def get_description(self):
        '''Return dc:description'''
        return self._get_metadata(constants.DC_DESCRIPTION_TAG, self.opf, as_string=True) or ''

    def get_publisher(self):
        return self._get_metadata(constants.DC_PUBLISHER_TAG, self.opf, plural=True) or []

    def get_toc_items(self):
        t = self.get_toc()
        return t.items

    def get_toc(self):
        if not self._parsed_toc:
            self._parsed_toc = TOC(self.toc, self.opf)
        return self._parsed_toc

    def get_last_chapter_read(self, user):
        '''Get the last chapter read by this user.'''
        ua = self.user_archive.filter(user=user, last_chapter_read__isnull=False).order_by('-id')
        if len(ua) > 0:
            return ua[0].last_chapter_read

    def explode(self):
        '''Explodes an epub archive'''
        z = ZipFile( self.name, 'r' ) # Returns a filehandle
        try:
            container = z.read(self._CONTAINER)
        except KeyError:
            # Is this DOS-format?  If so, handle this as a special error
            try:
                container = z.read(self._CONTAINER.replace('/', '\\'))
                raise InvalidEpubException("This ePub file was created with DOS/Windows path separators, which is not legal according to the PKZIP specification.")
            except KeyError:
                raise InvalidEpubException('Was not able to locate container file %s' % self._CONTAINER, archive=self)

        try:
            z.read(constants.RIGHTS)
            raise DRMEpubException()
        except KeyError:
            pass

        parsed_container = util.xml_from_string(container)

        opf_filename = self._get_opf_filename(parsed_container)

        content_path = self._get_content_path(opf_filename)
        self.opf = z.read(opf_filename)
        parsed_opf = util.xml_from_string(self.opf)

        items = [i for i in parsed_opf.iterdescendants(tag="{%s}item" % (NS['opf']))]

        toc_filename = self._get_toc(parsed_opf, items, content_path)
        try:
            self.toc = z.read(toc_filename)
        except KeyError:
            raise InvalidEpubException('TOC file was referenced in OPF, but not found in archive: toc file %s' % toc_filename, archive=self)

        parsed_toc = util.xml_from_string(self.toc)

        self.authors  = self._get_authors(parsed_opf)
        self.title    = self._get_title(parsed_opf)
        if self.use_spine_as_toc:
            self._get_content(z, parsed_opf, parsed_toc, items, content_path)
        else:
            self._get_content_from_nav_points(z, content_path)
        #self._get_images(z, items, content_path)


    def _get_opf_filename(self, container):
        '''Parse the container to get the name of the opf file'''
        try:
            return container.find('.//{%s}rootfile' % NS['container']).get('full-path')
        except AttributeError:
            # We couldn't find the OPF, probably due to a malformed container file
            raise InvalidEpubException("Bookworm was unable to open this ePub. Check that your META-INF/container.xml file is correct, including XML namespaces")

    def _get_content_path(self, opf_filename):
        '''Return the content path, which may be a named subdirectory or could be at the root of
        the archive'''
        if os.path.dirname(opf_filename) == "":
            return ""
        return os.path.dirname(opf_filename) + "/"

    def _get_toc(self, opf, items, content_path):
        '''Parse the opf file to get the name of the TOC
        (From OPF spec: The spine element must include the toc attribute,
        whose value is the the id attribute value of the required NCX document
        declared in manifest)'''
        spine = opf.find('.//{%s}spine' % NS['opf'])
        if spine is None:
            raise InvalidEpubException("Could not find an opf:spine element in this document")
        tocid = spine.get('toc')

        if tocid:
            try:
                toc_filename = opf.xpath('//opf:item[@id="%s"]' % (tocid),
                                         namespaces={'opf':NS['opf']})[0].get('href')
            except IndexError:
                raise InvalidEpubException("Could not find an item matching %s in OPF <item> list" % (tocid), archive=self)
        else:
            # Find by media type
            logging.warning("Did not have toc attribute on OPF spine; going to media-type")
            try:
                toc_filename = opf.xpath('//opf:item[@media-type="application/x-dtbncx+xml"]',
                                         namespaces={'opf': NS['opf']})[0].get('href')
            except IndexError:
                # Last ditch effort, find an href with the .ncx extension
                try:
                    toc_filename = opf.xpath('//opf:item[contains(@href, ".ncx")]',
                                             namespaces={'opf':NS['opf']})[0].get('href')
                except IndexError:
                    raise InvalidEpubException('Could not find any NCX file. EpubCheck 1.0.3 may erroneously report this as valid.', archive=self)
        return "%s%s" % (content_path, toc_filename)

    def _get_authors(self, opf):
        '''Retrieves a list of authors from the opf file, tagged as dc:creator.  It is acceptable
        to have no author or even an empty dc:creator'''
        authors = [a.text.strip() for a in opf.findall('.//{%s}%s' % (NS['dc'], constants.DC_CREATOR_TAG)) if a is not None and a.text is not None]
        if len(authors) == 0:
            logging.warning('Got empty authors string for book %s' % self.name)
        return authors

    def _get_title(self, xml):
        '''Retrieves the title from dc:title in the OPF'''
        title = xml.xpath('/opf:package/opf:metadata//dc:title/text()', namespaces={ 'opf': NS['opf'],
                                                                                    'dc': NS['dc']})
        if len(title) == 0:
            raise InvalidEpubException('This ePub document does not have a title.  According to the ePub specification, all documents must have a title.', archive=self)

        return title[0].strip()

    def _get_images(self, archive, items, content_path):
        '''Images might be in a variety of formats, from JPEG to SVG.  It may also be a video type, though hopefully the content creator included the required fallback.
        If they are SVG they need to be specially handled as a text type.'''
        images = []
        for item in items:
            if 'image' in item.get('media-type') or 'video' in item.get('media-type') or 'flash' in item.get('media-type'):

                href = unquote_plus(item.get('href'))

                try:
                    content = archive.read("%s%s" % (content_path, href))
                except KeyError:
                    logging.warning("Missing image %s; skipping" % href)
                    continue
                data = {}
                data['data'] = None
                data['file'] = None

                if item.get('media-type') == constants.SVG_MIMETYPE:
                    data['file'] = unicode(content, ENC)

                else:
                    # This is a binary file, like a jpeg
                    data['data'] = content

                (data['path'], data['filename']) = os.path.split(href)
                logging.debug('Got path=%s, filename=%s' % (data['path'], data['filename']))
                data['idref'] = item.get('id')
                data['content_type'] = item.get('media-type')

                images.append(data)

        self._create_images(images)

    def _create_images(self, images):
        pass
        #for i in images:
            #f = i['file']
            #if f == None:
                #f = ''
            #if self.ImageFile().objects.filter(filename=i['filename'],
                                                #archive=self).count() > 0:
                #logging.warning("Already had an image for archive %s with filename %s; skipping" % (self.name, i['filename']))
                #return
            #image = self.ImageFile()(
                #idref=i['idref'],
                #file=f,
                #filename=i['filename'],
                #data=i['data'],
                #path=i['path'],
                #content_type=i['content_type'],
                #archive=self)
            #image.save()

    def _get_content_from_nav_points(self, archive, content_path):
        toc_tree = self.get_toc().tree
        page_for_navpoint = {}
        for i in range(len(toc_tree)):
            current_nav_point = toc_tree[i]
            previous_anchor = None
            next_anchor = None
            if i != 0:
                previous_nav_point = toc_tree[i-1]
                if current_nav_point.href().split("#")[0] == previous_nav_point.href().split("#")[0]:
                    previous_anchor = {"title": previous_nav_point.title()}
                    try:
                        previous_anchor["id"] = previous_nav_point.href().split("#")[1]
                    except IndexError:
                        previous_anchor["id"] = None
            if i != len(toc_tree)-1:
                next_nav_point = toc_tree[i+1]
                if current_nav_point.href().split("#")[0] == next_nav_point.href().split("#")[0]:
                    next_anchor = {"id": next_nav_point.href().split("#")[1], "title": next_nav_point.title()}

            filename = "%s%s" %(content_path, current_nav_point.href().split("#")[0])
            try:
                content = archive.read(filename)
            except Exception:
                raise InvalidEpubException(
                    'Could not find file %s in archive even though it was listed in the NCX file' %filename,
                    archive=self
                )

            page = self._create_page(
                current_nav_point.title(),
                None,
                current_nav_point.href(),
                content,
                self,
                current_nav_point.order(),
                previous_anchor,
                next_anchor
            )
            self.pages.append(page)
            page.bind_to_parent(page_for_navpoint.get(current_nav_point.parent))
            if len(current_nav_point.find_children()) > 0:
                page_for_navpoint[current_nav_point] = page


    def _get_content(self, archive, opf, toc, items, content_path):
        # Get all the item references from the <spine>
        refs = opf.getiterator('{%s}itemref' % (NS['opf']) )
        navs = [n for n in toc.getiterator('{%s}navPoint' % (NS['ncx']))]
        navs2 = [n for n in toc.getiterator('{%s}navTarget' % (NS['ncx']))]
        navs = navs + navs2

        nav_map = {}
        item_map = {}

        for item in items:
            item_map[item.get('id')] = item.get('href')

        for nav in navs:
            n = NavPoint(nav, doc_title=self.title)
            href = n.href()
            filename = href.split('#')[0]
            if nav_map.has_key(filename):
                pass
                # Skip this item so we don't overwrite with a new navpoint
            else:
                nav_map[filename] = n

        idrefs_already_processed = set()

        for ref in refs:
            idref = ref.get('idref')
            if idref in idrefs_already_processed:
                continue

            idrefs_already_processed.add(idref)

            if item_map.has_key(idref):
                href = item_map[idref]
                filename = '%s%s' % (content_path, href)
                try:
                    content = archive.read(filename)
                except Exception:
                    raise InvalidEpubException('Could not find file %s in archive even though it was listed in the OPF file' % filename,
                                               archive=self)

                # We store the raw XHTML and will process it for display on request
                # later

                # If this item is in the navmap then we have a handy title
                if href in nav_map:
                    title = nav_map[href].title()
                    order = nav_map[href].order()
                else:
                    title = href.split('/')[-1]
                    order = 0

                page = {'title': title,
                        'path': os.path.split(title)[0],
                        'idref':idref,
                        'filename':href,
                        'file':content,
                        'archive':self,
                        'order':order}
                self.pages.append(self._create_page(
                    page['title'], page['idref'], page['filename'], page['file'], page['archive'], page['order']
                ))


    def _create_page(self, title, idref, filename, file_content, archive, order, previous_anchor=None, next_anchor=None):
        '''Create an HTML page and associate it with the archive'''
        return EpubPage(
                        title=title,
                        idref=idref,
                        filename=filename,
                        file_content=file_content,
                        archive=archive,
                        order=order,
                        previous_anchor=previous_anchor,
                        next_anchor=next_anchor
        )


    def _get_metadata(self, metadata_tag, opf, plural=False, as_string=False, as_list=False):
        '''Returns a metadata item's text content by tag name, or a list if mulitple names match.
        If as_string is set to True, then always return a comma-delimited string.'''
        if self._parsed_metadata is None:
            try:
                self._parsed_metadata = util.xml_from_string(opf)
            except InvalidEpubException:
                return None
        text = []
        alltext = self._parsed_metadata.findall('.//{%s}%s' % (NS['dc'], metadata_tag))
        if as_list:
            return [t.text.strip() for t in alltext if t.text]
        if as_string:
            return ', '.join([t.text.strip() for t in alltext if t.text])
        for t in alltext:
            if t.text is not None:
                text.append(t.text)
        if len(text) == 1:
            t = (text[0], ) if plural else text[0]
            return t
        return text

    def __unicode__(self):
        return u'%s by %s (%s)' % (self.title, self.author, self.name)


def normalize_text(text_content):
    """
    Replaces "&nbsp;" with spaces and subtitutes multiple spaces with single one
    """
    if not isinstance(text_content, unicode):
        text_content = unicode(text_content, "UTF-8")
    return " ".join(text_content.replace(u"\u00A0", " ").split())

def find_anchor_by_text(root_elem, text_content, cached_anchors = {}):
    """
    Find element with text_content text under root_elem element
    """
    root_elem_key = hashlib.sha224(root_elem.text_content().encode("utf-8")).hexdigest()
    if not cached_anchors.has_key(root_elem_key):
        cached_anchors[root_elem_key] = {}
        for header_tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            for elem in root_elem.cssselect("%s>a" %header_tag):
                cached_anchors[root_elem_key][elem.text_content()] = elem
    res = cached_anchors[root_elem_key].get(text_content)
    if res is None:
        raise Exception("Anchor with title '%s' is not found" %text_content)

class EpubPage(object):
    '''Usually an individual page in the ebook.'''
    
    def __init__(self, title, idref, filename, file_content, archive, order, previous_anchor = None, next_anchor = None):
        self.title_in_toc = title
        self.idref    = idref
        self.filename = filename
        self.page_content = normalize_text(file_content)
        self.archive  = archive
        self.order    = order or 1
        self.current_anchor = None
        self.parent_page = None
        self.previous_anchor = previous_anchor
        self.next_anchor = next_anchor
        if next_anchor is not None:
            self.current_anchor = {"title": self.title_in_toc}
            try:
                self.current_anchor["id"] = self.filename.split("#")[1]
            except IndexError:
                self.current_anchor["id"] = None
        elif previous_anchor is not None:
            self.current_anchor = {"title": self.title_in_toc}
            try:
                self.current_anchor["id"] = self.filename.split("#")[1]
            except IndexError:
                self.current_anchor["id"] = None
        self.page_content_parsed = self.parse_page_content(self.page_content)
        self.title_tag = self.page_content_parsed.find('.//title')
        self.sections = []
        self.children_pages = []
        self.parse_sections()

    def parse_page_content(self, page_content, cached_soup = {}):
        page_key = hashlib.sha224(page_content.encode("utf-8")).hexdigest()
        try:
            if not cached_soup.has_key(page_key):
                import lxml.html.soupparser
                cached_soup[page_key] = lxml.html.soupparser.fromstring(page_content)
            html = deepcopy(cached_soup[page_key])

            body = html.find('.//body')
            if body is None:
                raise UnknownContentException()
# for simplicity we decided to use BeatifulSoup parser for now
#            html = etree.XML(page_content, etree.XMLParser())
#            body = html.find('{%s}body' % NS['html'])
#            if body is None:
#                raise UnknownContentException()
        except (ExpatError, etree.XMLSyntaxError, UnknownContentException):
            raise
#            logging.warning('Was not valid XHTML; trying with BeautifulSoup')
#            try:
#                import lxml.html.soupparser
#                html = lxml.html.soupparser.fromstring(page_content)
#                body = html.find('.//body')
#                if body is None:
#                    raise
#                import pdb;pdb.set_trace()
#            except:
#                # Give up
#                logging.error("Giving up on this content")
#                raise UnknownContentException()
        if self.current_anchor is None:
            return html
        elements_to_remove = []
        if self.current_anchor["id"] is None:
            start_elem = None
        else:
            try:
                start_elem = body.cssselect("#%s" %self.current_anchor["id"])[0]
            except IndexError:
                start_elem = find_anchor_by_text(body, self.current_anchor["title"])
        if self.next_anchor is None:
            end_elem = None
        else:
            try:
                end_elem = body.cssselect("#%s" %self.next_anchor["id"])[0]
            except IndexError:
                end_elem = find_anchor_by_text(body, self.next_anchor["title"])

        within_start_and_end_elem = True if start_elem is None else False
        for elem in body.iter():
            if elem == start_elem:
                within_start_and_end_elem = True
            elif elem == end_elem:
                within_start_and_end_elem = False
            if not within_start_and_end_elem and start_elem not in elem.iterchildren() and end_elem not in elem.iterchildren():
                elements_to_remove.append(elem)

        for elem in elements_to_remove:
            elem.clear()
            try:
                body.remove(elem)
            except ValueError:
                pass
        return html

    def get_page_title(self):
        """
        1. If there is a non-empty <title></title> header in the page and there is no other pages
        with the same <title>, use it as the title.
        Otherwise:
        2. If there is a h1..h6 element in the body before any other text, and
        if this h1..h6 is the biggest header in the page, and if this header
        is unique (there is no other header of the same level in the page),
        use it as the title.
        Otherwise:
        3. Use the NCX navPoint->navLabel->text if non-empty
        Otherwise:
        4. Use the name from the spine
        """
        if [page.title_tag.text for page in self.archive.pages].count(self.title_tag.text) == 1:
            return self.title_tag.text
        elif len(self.sections) == 1 and self.sections[0].title:
            return self.sections[0].title
        elif self.title_in_toc:
            return self.title_in_toc
        else:
            return self.idref


    def parse_sections(self):
        """
        Parses page content and builds hierarchy of sections judging on h1 - h6 tags
        """
        heading_tags = ("h1", "h2", "h3", "h4", "h5", "h6")
        current_section = EpubPageSection(self)
        current_section.bind_to_parent(None)
        for elem in self.page_content_parsed.find(".//body").iter():
            if elem.tag in heading_tags:
                heading_text = " ".join([t.strip() for t in elem.itertext()])
                heading_level = int(elem.tag[1])
                if current_section.title is None and not current_section.has_text_before_title:
                    current_section.title = heading_text
                    current_section.title_level = heading_level
                else:
                    new_section = EpubPageSection(self, heading_text)
                    new_section.title = heading_text
                    new_section.title_level = heading_level
                    if current_section.title is None:
                        new_section.bind_to_parent(None)
                    elif new_section.title_level > current_section.title_level:
                        new_section.bind_to_parent(current_section)
                    elif new_section.title_level == current_section.title_level:
                        new_section.bind_to_parent(current_section.parent_section)
                    else:
                        parent = current_section.find_ancestor_with_title_level_less_than(
                            new_section.title_level
                        )
                        new_section.bind_to_parent(parent)
                    current_section = new_section
            else:
                if (not current_section.has_text_before_title
                and current_section.title is None
                and elem.text is not None
                and elem.text.strip()
                ):
                    current_section.has_text_before_title = True
                    if (elem.getparent() not in current_section.content_elements
                        and elem.getparent().tag not in heading_tags # skip children of heading tag, as they are part of the title
                    ):
                        current_section.content_elements.append(elem)

    # XHTML content that has been sanitized.  This isn't done until
    # the user requests to access the file or until the automated
    # process hits it, whichever occurs first
    #processed_content = models.TextField(null=True)

    def render(self, user=None):
        '''If we don't have any processed content, process it and cache the
        results in the database.'''

        if hasattr(self,'processed_content'):
            return self.processed_content

        if self.title_tag is not None:
          print "TITLE: " + self.get_page_title() + "\n\n"
        body = self._clean_xhtml(self.page_content_parsed.find('.//body'))
        return lxml.html.tostring(body, encoding=ENC, method="html")


    def _clean_xhtml(self, xhtml):
        '''This is only run the first time the user requests the HTML file; the processed HTML is then cached'''
        ns = u'{%s}' % NS['html']
        nsl = len(ns)
        for element in xhtml.getiterator():
            if type(element.tag) == str and element.tag.startswith(ns):
                element.tag = element.tag[nsl:]

            # if we have SVG, then we need to re-write the image links that contain svg in order to
            # make them work in most browsers
            if element.tag == 'img' and element.get('src') is not None and 'svg' in element.get('src'):
                    p = element.getparent()
                    e = etree.fromstring("""<a class="svg" href="%s">[ View linked image in SVG format ]</a>""" % element.get('src'))
                    p.remove(element)
                    p.append(e)

            # Script tags are removed
            if element.tag == 'script':
                p = element.getparent()
                p.remove(element)
            # So are links which have javascript: in them
            if element.get('href') and 'javascript:' in element.get('href'):
                element.set('href', '#')

        return xhtml

    def bind_to_parent(self, parent_page):
        self.parent_page = parent_page
        if parent_page is not None:
            parent_page.children_pages.append(self)

    def add_children_page(self, children_page):
        self.children_pages.append(children_page)
        children_page.parent_page = self


class EpubPageSection(object):

    def __init__(self, page, title = None):
        self.has_text_before_title = False
        self.title = None
        self.title_level = 0
        self.parent_section = None
        self.children_sections = []
        self.content_elements = []
        self.page = page

    def bind_to_parent(self, parent_section):
        """Binds current section to some parent section. If parent section is None - bind it to page itself"""
        self.parent_section = parent_section
        if parent_section is None:
            self.page.sections.append(self)
        else:
            parent_section.children_sections.append(self)

    def find_ancestor_with_title_level_less_than(self, level):
        """Does what function name says. Result is used as parent for new section with title_level = level"""
        current_section = self
        while current_section is not None:
            if current_section.parent_section and current_section.parent_section.title_level < level:
                return current_section.parent_section
            current_section = current_section.parent_section
        return current_section # i.e. None, there is no such ancestor

class InvalidBinaryException(InvalidEpubException):
    pass

class DRMEpubException(Exception):
    pass

class UnknownContentException(InvalidEpubException):
    # We weren't sure how to parse the body content here
    pass                
                 

