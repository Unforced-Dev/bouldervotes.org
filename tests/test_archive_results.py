"""Past elections open with results; every candidate and measure remains linked."""
from __future__ import annotations
import sqlite3
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DOCS=ROOT/'docs'
YEARS=(2017,2019,2021,2023,2025)

class Headings(HTMLParser):
    def __init__(self):
        super().__init__();self.headings=[];self.active=None
    def handle_starttag(self,tag,attrs):
        if tag in ('h1','h2','h3'):
            self.active=[tag,dict(attrs).get('id'), '']
    def handle_data(self,data):
        if self.active:self.active[2]+=data
    def handle_endtag(self,tag):
        if self.active and tag==self.active[0]:
            self.headings.append(tuple(self.active));self.active=None

class TestArchiveResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con=sqlite3.connect(ROOT/'data'/'bouldervotes.db')
    @classmethod
    def tearDownClass(cls):cls.con.close()

    def test_results_before_races_questions_last(self):
        for year in YEARS:
            with self.subTest(year=year):
                html=(DOCS/f'{year}.html').read_text()
                p=Headings();p.feed(html.split('<footer class="site"')[0])
                headings=p.headings
                sections=[(i,id,text) for i,(_,id,text) in enumerate(headings) if id]
                ids=[id for _,id,_ in sections]
                self.assertLess(ids.index('outcome'),ids.index('council'))
                self.assertLess(ids.index('council'),ids.index('measures'))
                if 'questions' in ids:
                    self.assertGreater(ids.index('questions'),ids.index('measures'))
                    self.assertIn('Questions asked', headings[-1][2])
                self.assertIn('Elected',html)
                self.assertIn('Official',html)
                self.assertIn('archive-mono',html)

    def test_every_candidate_and_measure_has_results(self):
        for year in YEARS:
            s=(DOCS/f'{year}.html').read_text()
            candidates=self.con.execute('''SELECT p.full_name,p.slug,res.votes
                 FROM candidacies c JOIN people p ON p.id=c.person_id
                 JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
                 LEFT JOIN results res ON res.candidacy_id=c.id
                 AND res.round=(SELECT max(rr.round) FROM results rr WHERE rr.candidacy_id=c.id)
                 WHERE e.year=?''',(year,)).fetchall()
            for name,slug,votes in candidates:
                with self.subTest(year=year,candidate=name):
                    self.assertIn(name,s)
                    self.assertIn(f'people/{slug}.html',s)
                    if votes is not None:self.assertIn(f'{votes:,}',s)
            measures=self.con.execute('''SELECT m.letter,mr.yes_votes,mr.no_votes
                 FROM measures m JOIN elections e ON e.id=m.election_id
                 LEFT JOIN measure_results mr ON mr.measure_id=m.id WHERE e.year=?''',(year,)).fetchall()
            for letter,yes,no in measures:
                with self.subTest(year=year,measure=letter):
                    self.assertIn(letter,s)
                    if yes is not None:
                        self.assertIn(f'{yes:,}',s)
                        self.assertIn(f'{yes/(yes+no)*100:.1f}%',s)

    def test_rcv_rounds_not_just_finalists(self):
        s=(DOCS/'2023.html').read_text()
        self.assertIn('Round 1',s);self.assertIn('Round 2',s)
        self.assertIn('16,823',s);self.assertIn('51.9%',s)

if __name__=='__main__':unittest.main()
