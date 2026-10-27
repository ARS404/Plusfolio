#!/usr/bin/env python3
"""Fetch the public problems.ru subject taxonomy, never tasks or solutions.

Uses the public subject selector discovered at
https://www.problems.ru/subject_select_new.php?id1=search2_subject_text_3&id2=search2_subject_hidden_3&parent=189
The selector exposes every direct child and marks children that can be opened;
therefore terminal subject pages never need to be requested. Requests are serial,
cached and resumable, respect robots.txt and use at least its 20 s Crawl-delay.

Examples:
  python3 scripts/fetch_topics.py --max-fetches 22
  python3 scripts/fetch_topics.py --max-fetches 0  # resume to completion
  python3 scripts/fetch_topics.py --offline       # regenerate from cache

Only names, numeric source IDs, source edges and metadata are saved. No task
statements, solutions, counts of tasks, or personal data are collected.
"""
from __future__ import annotations
import argparse
import ast
from collections import defaultdict, deque
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

BASE = 'https://problems.ru'
CATALOG_URL = BASE + '/view_by_subject_new.php?parent='
ROOT_ID = '1302'
ROOT_NAME = 'Все темы'
AGENT = 'PlusfolioTopicCatalog/0.1 (local design research; taxonomy only)'
MIN_DELAY = 20.0


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def selector_url(source_id):
    return BASE + '/subject_select_new.php?' + urlencode({
        'id1': 'search2_subject_text_3', 'id2': 'search2_subject_hidden_3',
        'parent': source_id,
    })


def subject_url(source_id):
    return BASE + '/view_by_subject_new.php?parent=' + str(source_id)


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self.current = None
        self.title = ''
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag == 'a':
            self.current = {'href': attrs.get('href', ''), 'text': ''}

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'a' and self.current is not None:
            self.current['text'] = ' '.join(self.current['text'].split())
            self.anchors.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data
        if self.in_title:
            self.title += data


def js_string(value):
    # The site uses quoted JS string literals in its public selection links.
    # Parse a single literal as data; never execute JavaScript.
    try:
        return ast.literal_eval("'" + value + "'")
    except (SyntaxError, ValueError):
        return value.replace("\\'", "'").replace('\\\\', '\\')


def parse_selector(html, source_id):
    parser = AnchorParser()
    parser.feed(html)
    if parser.title.strip() != 'Выбор темы':
        raise ValueError('Unexpected selector title: ' + parser.title[:120])
    children = []
    drillable = set()
    up_id = None
    pattern = re.compile(r"^javascript:doSelectParam\('(?:\\.|[^'])*','(?:\\.|[^'])*','((?:\\.|[^'])*)',(\d+)\)$")
    for anchor in parser.anchors:
        href, text = anchor['href'], anchor['text']
        match = pattern.match(href)
        if match:
            children.append({'source_id': match.group(2), 'name': js_string(match.group(1))})
        elif href.startswith('?'):
            child_id = parse_qs(urlparse(href).query).get('parent', [None])[0]
            if text == 'На уровень вверх':
                up_id = child_id
            elif child_id and child_id.isdigit():
                drillable.add(child_id)
    ids = [n['source_id'] for n in children]
    if len(ids) != len(set(ids)):
        raise ValueError('Repeated child ID in selector ' + source_id)
    for child in children:
        child['has_children'] = child['source_id'] in drillable
        child['source_url'] = subject_url(child['source_id'])
    # A valid root and a drilled internal node must have children.
    if not children:
        raise ValueError('No selectable children found at ' + source_id)
    unexpected = drillable - set(ids)
    if unexpected:
        raise ValueError('Drillable ID missing from children: ' + repr(unexpected))
    return {'source_id': source_id, 'parent_source_id_from_up_link': up_id, 'children': children}


class Fetcher:
    def __init__(self, cache_dir, requested_delay, offline):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = max(MIN_DELAY, requested_delay)
        self.offline = offline
        self.state_path = self.cache_dir / 'fetch-state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.robot = RobotFileParser()
        self.robot.set_url(BASE + '/robots.txt')
        robots_path = self.cache_dir / 'robots.json'
        if robots_path.exists() and (offline or time.time() - robots_path.stat().st_mtime < 86400):
            robots = json.loads(robots_path.read_text())
        elif offline:
            raise RuntimeError('Offline cache has no robots.txt')
        else:
            text = self.request(BASE + '/robots.txt', check_robots=False)
            robots = {'source_url': BASE + '/robots.txt', 'fetched_at': utc_now(), 'text': text}
            save_json(robots_path, robots)
        self.robots = robots
        self.robot.parse(robots['text'].splitlines())
        delay = self.robot.crawl_delay(AGENT) or self.robot.crawl_delay('*')
        if delay:
            self.delay = max(self.delay, float(delay))

    def request(self, url, check_robots=True):
        if self.offline:
            raise RuntimeError('Network request in offline mode')
        if check_robots and not self.robot.can_fetch(AGENT, url):
            raise RuntimeError('robots.txt disallows ' + url)
        failure = None
        for attempt in range(4):
            since = time.time() - self.state.get('last_request_epoch', 0)
            remaining = self.delay - since
            if remaining > 0:
                time.sleep(remaining)
            self.state['last_request_epoch'] = time.time()
            save_json(self.state_path, self.state)
            try:
                req = Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain;q=0.8'})
                with urlopen(req, timeout=30) as response:
                    # Selector pages contain metadata only; no problem page is fetched.
                    data = response.read(2_000_000)
                    if len(data) >= 2_000_000:
                        raise ValueError('Unexpectedly large selector response')
                    return data.decode(response.headers.get_content_charset() or 'utf-8')
            except (HTTPError, URLError, TimeoutError) as error:
                failure = error
                if isinstance(error, HTTPError) and error.code in {401, 403, 404}:
                    break
                time.sleep(min(60, 5 * (2 ** attempt)))
        raise RuntimeError('Fetch failed: ' + url + ' (' + str(failure) + ')')

    def get(self, source_id, allow_network):
        cache_path = self.cache_dir / (source_id + '.json')
        if cache_path.exists():
            return json.loads(cache_path.read_text()), False
        if not allow_network or self.offline:
            return None, False
        url = selector_url(source_id)
        parsed = parse_selector(self.request(url), source_id)
        parsed['selector_url'] = url
        parsed['fetched_at'] = utc_now()
        save_json(cache_path, parsed)
        return parsed, True


def build_catalog(fetcher, max_fetches, output):
    nodes = {ROOT_ID: {'source_id': ROOT_ID, 'parent_source_id': None, 'name': ROOT_NAME,
        'source_url': subject_url(ROOT_ID), 'sort_order': 0, 'has_children': True,
        'children_complete': False}}
    edges = []
    conflicts, failures = [], []
    pending, visited, queue = [], set(), deque([ROOT_ID])
    deferred, cache_phase = [], True
    requests_made = 0
    pages = []
    # Reconstruct every reachable cached branch before any network request.
    # Resuming must not temporarily remove known topics from the saved asset.
    while queue or (cache_phase and deferred):
        if not queue:
            cache_phase = False
            queue.extend(deferred)
            deferred = []
        source_id = queue.popleft()
        if source_id in visited:
            continue
        allow_network = not cache_phase and (max_fetches == 0 or requests_made < max_fetches)
        try:
            page, made = fetcher.get(source_id, allow_network)
            requests_made += int(made)
        except Exception as error:
            failures.append({'source_id': source_id, 'error': str(error), 'at': utc_now()})
            pending.append(source_id)
            visited.add(source_id)
            continue
        if page is None:
            if cache_phase:
                deferred.append(source_id)
            else:
                pending.append(source_id)
                visited.add(source_id)
            continue
        visited.add(source_id)
        pages.append({'source_id': source_id, 'fetched_at': page['fetched_at'], 'selector_url': page['selector_url']})
        nodes[source_id]['children_complete'] = True
        up_id = page['parent_source_id_from_up_link']
        if source_id != ROOT_ID and up_id != nodes[source_id]['parent_source_id']:
            conflicts.append({'type': 'up_link_parent_mismatch', 'source_id': source_id,
                'selected_parent': nodes[source_id]['parent_source_id'], 'up_link_parent': up_id})
        for order, child in enumerate(page['children']):
            child_id = child['source_id']
            edge = {'parent_source_id': source_id, 'child_source_id': child_id, 'sort_order': order}
            edges.append(edge)
            if child_id in nodes:
                if nodes[child_id]['parent_source_id'] != source_id:
                    conflicts.append({'type': 'multiple_parent_or_cycle', 'source_id': child_id,
                        'selected_parent': nodes[child_id]['parent_source_id'], 'extra_parent': source_id})
                if nodes[child_id]['name'] != child['name']:
                    conflicts.append({'type': 'name_conflict', 'source_id': child_id,
                        'selected_name': nodes[child_id]['name'], 'extra_name': child['name']})
            else:
                nodes[child_id] = dict(child, parent_source_id=source_id, sort_order=order,
                    children_complete=not child['has_children'])
            if child['has_children'] and child_id not in visited:
                queue.append(child_id)
        # Save after each network response, so an interruption still leaves a usable asset.
        if made:
            print(f"fetched={requests_made} pages={len(pages)} topics={len(nodes)} queue={len(queue)} current={source_id}", flush=True)
        if made:
            write_output(output, nodes, edges, conflicts, failures, pending + list(queue) + deferred, pages, fetcher, requests_made)
    write_output(output, nodes, edges, conflicts, failures, pending, pages, fetcher, requests_made)
    return {'source_topics_including_root': len(nodes), 'pages_parsed': len(pages),
            'unexpanded_branches': len(set(pending)), 'complete': not pending and not failures,
            'conflicts': len(conflicts), 'network_pages_this_run': requests_made}


def write_output(output, nodes, edges, conflicts, failures, pending, pages, fetcher, requests_made):
    pending = sorted(set(pending), key=lambda x: int(x))
    source_nodes = sorted(nodes.values(), key=lambda n: int(n['source_id']))
    # Existing terminal '(прочее)' children become the system Other node. Preserve
    # their ID/name/URL for traceability, instead of showing duplicate Other choices.
    other_pattern = re.compile(r'(?:\(прочее\)|\bпрочее)$', re.I)
    selected_other = {}
    for node in source_nodes:
        if node['source_id'] != ROOT_ID and other_pattern.search(node['name']) and not node['has_children']:
            parent = node['parent_source_id']
            if parent not in selected_other:
                selected_other[parent] = node['source_id']
    normalized = []
    for node in source_nodes:
        source_id, parent = node['source_id'], node['parent_source_id']
        is_other = selected_other.get(parent) == source_id
        normalized.append({
            'id': ('other:problems:' + parent) if is_other else ('problems:' + source_id),
            'parent_id': 'problems:' + parent if parent else None,
            'name': 'Прочее' if is_other else node['name'],
            'source_id': source_id, 'parent_source_id': parent,
            'source_name': node['name'], 'source_url': node['source_url'],
            'is_other': is_other, 'is_system': is_other,
            'sort_order': 2147483647 if is_other else node['sort_order'],
            'source_children_complete': node['children_complete'],
        })
        if not is_other and source_id not in selected_other:
            normalized.append({
                'id': 'other:problems:' + source_id,
                'parent_id': 'problems:' + source_id,
                'name': 'Прочее', 'source_id': None, 'parent_source_id': None,
                'source_name': None, 'source_url': None,
                'is_other': True, 'is_system': True, 'sort_order': 2147483647,
                'source_children_complete': True,
            })
    # Referential validity and acyclicity are guaranteed by first-discovery BFS.
    by_id = {n['id']: n for n in normalized}
    assert len(by_id) == len(normalized)
    for node in normalized:
        if node['parent_id']:
            assert node['parent_id'] in by_id
        seen, current = set(), node
        while current['parent_id']:
            assert current['id'] not in seen, 'Cycle in normalized topics'
            seen.add(current['id'])
            current = by_id[current['parent_id']]
        if node['is_other']:
            assert not any(n['parent_id'] == node['id'] for n in normalized)
    ordinary_ids = {n['id'] for n in normalized if not n['is_other']}
    for normal_id in ordinary_ids:
        assert sum(n['parent_id'] == normal_id and n['is_other'] for n in normalized) == 1
    metadata = {
        'schema_version': 1, 'source': 'problems.ru public subject selector',
        'source_catalog_url': CATALOG_URL, 'source_root_id': ROOT_ID,
        'generated_at': utc_now(), 'time_zone': 'UTC',
        'complete': not pending and not failures,
        'completeness_scope': 'Topics reachable from the mathematical Все темы root 1302; excludes disconnected subject roots (e.g. Informatics).',
        'unexpanded_branch_source_ids': pending,
        'source_topic_count_including_root': len(source_nodes),
        'normalized_topic_count_including_root_and_other': len(normalized),
        'other_count': sum(n['is_other'] for n in normalized),
        'selector_pages_parsed': len(pages), 'network_selector_pages_this_run': requests_made,
        'minimum_request_interval_seconds': fetcher.delay,
        'robots': fetcher.robots,
        'data_excluded': ['problem statements', 'solutions', 'personal data', 'problem counts'],
        'normalization': [
            'Every ordinary topic, including the technical root and source leaves, has exactly one terminal system child Прочее.',
            'Existing terminal subjects whose source name ends in (прочее) are reused as system Other; source_name and source_id are retained.',
            'For multiple parents/cycles, first-discovery breadth-first parent wins; all observed edges and conflicts are retained.',
            'Missing branch expansions are explicitly marked; unobserved topics are never invented.',
            'System Other IDs are stable per parent (other:problems:<parent_id>); discovering an original source Other later adds traceability without changing its normalized ID.',
        ],
        'source_pages': pages,
    }
    save_json(output, {'metadata': metadata, 'source_nodes': source_nodes,
        'source_edges': edges, 'normalized_nodes': normalized,
        'conflicts': conflicts, 'fetch_failures': failures})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', default=str(Path(__file__).resolve().parents[1]/'.local'/'topics-cache'))
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1]/'data'/'problems_topics.json'))
    parser.add_argument('--max-fetches', type=int, default=22, help='Maximum new selector pages; 0 means no limit.')
    parser.add_argument('--delay', type=float, default=20, help='Minimum delay; cannot go below robots delay or 20 s.')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.max_fetches < 0:
        parser.error('--max-fetches must be >= 0')
    fetcher = Fetcher(args.cache_dir, args.delay, args.offline)
    print(json.dumps(build_catalog(fetcher, args.max_fetches, args.output), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
