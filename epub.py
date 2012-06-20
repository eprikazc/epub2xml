# -*- coding: utf-8 -*-
#from django.utils.translation import ugettext_lazy as _

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

    def __init__(self, basename):
        self.name = basename
        self.title = None
        self.opf = None
        self.authors = None
        self.toc = None
        self.pages = []
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
        self._get_content(z, parsed_opf, parsed_toc, items, content_path)
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


    def _create_page(self, title, idref, filename, f, archive, order):
        '''Create an HTML page and associate it with the archive'''
        return EpubPage(
                        title=title,
                        idref=idref,
                        filename=filename,
                        epubfile=f,
                        archive=archive,
                        order=order)


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




class EpubPage(object):
    '''Usually an individual page in the ebook.'''
    
    def __init__(self, title, idref, filename, epubfile, archive, order):
        self.title    = title
        self.idref    = idref
        self.filename = filename
        self.epubfile = epubfile
        self.archive  = archive
        self.order    = order or 1
        

    # XHTML content that has been sanitized.  This isn't done until
    # the user requests to access the file or until the automated
    # process hits it, whichever occurs first
    #processed_content = models.TextField(null=True)


    def render(self, user=None):
        '''If we don't have any processed content, process it and cache the
        results in the database.'''

        if hasattr(self,'processed_content'):
            return self.processed_content

        f = self.epubfile
        try:
            xhtml = etree.XML(f, etree.XMLParser())
            body = xhtml.find('{%s}body' % NS['html'])
            head = xhtml.find('{%s}head' % NS['html'])
            if body is None:
                raise UnknownContentException()
        except (ExpatError, etree.XMLSyntaxError, UnknownContentException):
            logging.warning('Was not valid XHTML; trying with BeautifulSoup')
            try:
                html = lxml.html.soupparser.fromstring(f)
                body = html.find('.//body')
                head = html.find('.//head')
                if body is None:
                    raise
            except:
                # Give up
                logging.error("Giving up on this content")
                raise UnknownContentException()

       
        headTitle = xhtml.find('.//title')
        if headTitle is not None:
          print "TITLE: " + headTitle + "\n\n"
          
        body = self._clean_xhtml(body)
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


class InvalidBinaryException(InvalidEpubException):
    pass

class DRMEpubException(Exception):
    pass

class UnknownContentException(InvalidEpubException):
    # We weren't sure how to parse the body content here
    pass                
                 

