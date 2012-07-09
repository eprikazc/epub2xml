from epub import EpubArchive, EpubPageSection
from lxml import etree

def convert_xhtml_elements(xhtml_elements):
    if xhtml_elements:
        xhtml_elements.insert(0, etree.Comment("BEGIN XHTML CONTENT"))
        xhtml_elements.append(etree.Comment("END XHTML CONTENT"))
    return xhtml_elements

def add_element_with_text(target_element, tag, text):
    elem = etree.Element(tag)
    elem.text = text
    target_element.append(elem)
    return elem

def epub_page_section_to_netilt(section, element_name):
    section_elem = etree.Element(element_name)
    if section.title is not None:
        add_element_with_text(section_elem, "title", section.title)

    xhtml_elements = []
    for (index, elem) in enumerate(section.content_elements):
        if isinstance(elem, EpubPageSection):
            section_elem.extend(convert_xhtml_elements(xhtml_elements))
            xhtml_elements = []
            section_elem.append(epub_page_section_to_netilt(elem, "subsection"))
        else:
            xhtml_elements.append(elem)
    section_elem.extend(convert_xhtml_elements(xhtml_elements))
    return section_elem


class NetiltDoc(object):
    def __init__(self, epub_filename):
        self.epub_filename = epub_filename
        self.epub_archive = None
        self.chapter_elements = {}
    def process(self, use_spine_as_toc):
        self.epub_archive = EpubArchive(self.epub_filename, use_spine_as_toc)
        document = etree.Element("document")
        add_element_with_text(document, "title", self.epub_archive.title)
        add_element_with_text(document, "authors", ", ".join(self.epub_archive.authors))

        for page in self.epub_archive.pages:
            page_root_elem = self.chapter_elements.get(page.parent_page, document)
            page_elem = etree.Element("page")
            if page.children_pages:
                add_element_with_text(page_elem, "title", "Overview")
                chapter_elem = etree.Element("chapter")
                if page.get_page_title() is not None:
                    add_element_with_text(chapter_elem, "title", page.get_page_title())
                page_root_elem.append(chapter_elem)
                self.chapter_elements[page] = chapter_elem
                page_root_elem = chapter_elem
            page_root_elem.append(page_elem)
            for section in page.sections:
                page_elem.append(epub_page_section_to_netilt(section, "section"))

        return etree.tostring(document, xml_declaration=True, encoding="UTF-8", pretty_print=True)
