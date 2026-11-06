"""Case studies are discovered from current first-party links, never fixed IDs."""
from flytbase_bdr.story_discovery import story_links_from_html


def test_directory_rank_changes_with_inbound_lead():
    html = '''<a href="/case-studies/sqm-chile-inspection">SQM mining inspection with Adentu</a>
              <a href="/case-studies/anglo-peru-mine">Anglo American mining survey in Peru</a>
              <a href="/case-studies/port-harbour">Harbour security operations at a port</a>
              <a href="https://evil.example/case-studies/mine">SQM fake story</a>'''
    mining = {"company": "Sociedad Quimica y Minera de Chile (SQM)", "industry": "mining",
              "referral": "Anglo American", "need": "autonomous mine inspection"}
    selected = story_links_from_html(html, mining)
    assert len(selected) >= 2
    assert selected[0]["url"].endswith("/sqm-chile-inspection")
    assert all("evil.example" not in row["url"] for row in selected)
    harbour = {"company": "Port Authority", "industry": "shipping", "referral": "",
               "need": "harbour perimeter security"}
    selected_port = story_links_from_html(html, harbour)
    assert len(selected_port) == 1 and selected_port[0]["url"].endswith("/port-harbour")


def test_no_interesting_case_returns_empty_not_fake_winner():
    html = '<a href="/case-studies/sqm-chile-inspection">SQM mining inspection</a>'
    lead = {"company": "Example Retail", "industry": "retail", "referral": "",
            "need": "inventory tracking"}
    assert story_links_from_html(html, lead) == []
