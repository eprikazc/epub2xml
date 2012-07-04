from unittest import TestCase
from epub import EpubPage, EpubArchive

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

class PagesFromNavPointsTest(TestCase):
    def test_nav_alice_short(self):
        simple_archive = EpubArchive("test_data/in1.epub", False)
        self.assertEqual(len(simple_archive.pages), 4) # all pages besides Cover

    def test_nested_pages(self):
        archive = EpubArchive("test_data/nested_navpoints.epub", False)
        self.assertEqual(len(archive.pages), 29)
        self.assertEqual(
            archive.pages[11].get_page_title(),
            'Additional SQL Server 2008 R2 Enhancements for DBAs'
        )
        self.assertEqual(
            archive.pages[11].parent_page.get_page_title(),
            'SQL Server 2008 R2 Enhancements for DBAs'
        )
        self.assertEqual(
            archive.pages[11].parent_page,
            archive.pages[9]
        )
        self.assertEqual(
            archive.pages[9].parent_page.get_page_title(),
            "CHAPTER 1 SQL Server 2008 R2 Editions and Enhancements"
        )
        self.assertEqual(
            archive.pages[9].parent_page,
            archive.pages[8]
        )
        self.assertEqual(
            archive.pages[8].parent_page.get_page_title(),
            "Part I Database Administration"
        )
        self.assertEqual(
            archive.pages[8].parent_page,
            archive.pages[7]
        )
        self.assertEqual(
            archive.pages[7].parent_page,
            None
        )
        self.assertEqual(
            [p.get_page_title() for p in archive.pages[7].children_pages],
            ["CHAPTER 1 SQL Server 2008 R2 Editions and Enhancements", "CHAPTER 10 Self-Service Analysis with PowerPivot"]
        )

    def test_very_first_page_in_doc(self):
        archive = EpubArchive("test_data/nested_navpoints.epub", False)
        page = archive.pages[8]
        self.assertEqual(
            page.get_page_title(),
            "CHAPTER 1 SQL Server 2008 R2 Editions and Enhancements"
        )
        self.assertEqual(
            len(page.page_content_parsed.find(".//body")),
            3 # h2, p, p
        )
        self.assertTrue(
            page.page_content_parsed.find(".//body").text_content().strip().endswith(
            "installation strategies are also identified."
        ))

    def test_middle_page(self):
        archive = EpubArchive("test_data/nested_navpoints.epub", False)
        page = archive.pages[11]
        self.assertEqual(
            page.get_page_title(),
            "Additional SQL Server 2008 R2 Enhancements for DBAs"
        )
        self.assertEqual(
            len(page.page_content_parsed.find(".//body")),
            3 # h4, p, ul
        )
        self.assertTrue(
            page.page_content_parsed.find(".//body").text_content().strip().endswith(
            "operating systems that support Extended Protection."
        ))
    def test_very_last_page_in_doc(self):
        archive = EpubArchive("test_data/nested_navpoints.epub", False)
        page = archive.pages[18]
        self.assertEqual(
            page.get_page_title(),
            "Side-by-Side Migration"
        )
        self.assertTrue(
            page.page_content_parsed.find(".//body").text_content().strip().endswith(
                "after the migration is complete."
            ))


class PagesFromSpineTest(TestCase):
    def test_alice_short(self):
        archive = EpubArchive("test_data/in1.epub")
        self.assertEqual(len(archive.pages), 5)