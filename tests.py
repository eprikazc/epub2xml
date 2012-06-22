from unittest import TestCase
from epub import EpubPage

class PageSectionTest(TestCase):
    def test_top_level_heading(self):
        in_html = open("test_data/page_sections/in1.html").read()
        page = EpubPage(None, None, None, in_html, None, None)
        self.assertEqual(len(page.sections), 1)
        self.assertEqual(page.sections[0].title, "Git Basics")
        nested_sections = page.sections[0].children_sections
        self.assertEqual(5, len(nested_sections))
        self.assertEqual(nested_sections[0].title, "Snapshots, Not Differences")
        self.assertEqual(nested_sections[1].title, "Nearly Every Operation Is Local")
        self.assertEqual(nested_sections[2].title, "Git Has Integrity")
        self.assertEqual(nested_sections[3].title, "Git Generally Only Adds Data")
        self.assertEqual(nested_sections[4].title, "The Three States")

    def test_multiple_headings(self):
        in_html = open("test_data/page_sections/in2.html").read()
        page = EpubPage(None, None, None, in_html, None, None)
        self.assertEqual(len(page.sections), 6)
        self.assertEqual(page.sections[0].title, "Git Basics")
        self.assertEqual(page.sections[1].title, "Snapshots, Not Differences")
        self.assertEqual(page.sections[2].title, "Nearly Every Operation Is Local")
        self.assertEqual(page.sections[3].title, "Git Has Integrity")
        self.assertEqual(page.sections[4].title, "Git Generally Only Adds Data")
        self.assertEqual(page.sections[5].title, "The Three States")

    def test_no_first_heading(self):
        in_html = open("test_data/page_sections/in3.html").read()
        page = EpubPage(None, None, None, in_html, None, None)
        self.assertEqual(len(page.sections), 6)
        self.assertEqual(page.sections[0].title, None)
        self.assertEqual(page.sections[1].title, "Snapshots, Not Differences")
        self.assertEqual(page.sections[2].title, "Nearly Every Operation Is Local")
        self.assertEqual(page.sections[3].title, "Git Has Integrity")
        self.assertEqual(page.sections[4].title, "Git Generally Only Adds Data")
        self.assertEqual(page.sections[5].title, "The Three States")

    def test_complex_nested_sections(self):
        in_html = open("test_data/page_sections/in4.html").read()
        page = EpubPage(None, None, None, in_html, None, None)
        self.assertEqual(len(page.sections), 3)
        self.assertEqual(page.sections[0].title, "Git Basics")
        section1_children = page.sections[0].children_sections
        self.assertEqual(len(section1_children), 1)
        self.assertEqual(section1_children[0].title, "Snapshots, Not Differences")
        self.assertEqual(len(section1_children[0].children_sections), 1)
        self.assertEqual(section1_children[0].children_sections[0].title, "Nearly Every Operation Is Local")

        self.assertEqual(page.sections[1].title, "Git Has Integrity")
        self.assertEqual(len(page.sections[1].children_sections), 1)
        self.assertEqual(page.sections[1].children_sections[0].title, "Git Generally Only Adds Data")

        self.assertEqual(page.sections[2].title, "The Three States")
        self.assertEqual(page.sections[2].children_sections, [])
