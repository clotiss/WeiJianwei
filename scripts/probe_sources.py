"""Read-only live validation of registered policy source adapters."""
import json
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from policy_v2.network import SafeFetcher
from policy_v2.parsing import parse_detail, parse_list
from policy_v2.settings import Settings
from policy_v2.sources import SPECS, source_config


def describe_error(exc):
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
    return f"{type(current).__name__}:{str(current)[:240]}"


def validate_source(fetcher, spec, pages=1):
    source_id, name, region, kind, url, adapter, selector, hosts = spec
    config = source_config(spec)
    result = {"id": source_id, "url": url, "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        data, mime, final_url = fetcher.get(url, hosts, page_kind='list', config=config)
        result.update(
            list_fetch_status="ok",
            list_http_status=fetcher.last_status,
            list_initial_http_status=fetcher.initial_status,
            list_fetch_mode=fetcher.last_mode,
            mime=mime,
            bytes=len(data),
            final_url=final_url,
        )
    except Exception as exc:
        result.update(
            list_fetch_status="error",
            list_http_status=fetcher.last_status,
            list_initial_http_status=fetcher.initial_status,
            list_fetch_mode=fetcher.last_mode,
            fetch_error=describe_error(exc),
        )
        return result

    try:
        items, next_url = parse_list(data, final_url, config)
        result.update(
            list_status="ok",
            item_count=len(items),
            sample_title=items[0]["title"] if items else '',
            sample_url=items[0]["url"] if items else '',
            next_page=next_url,
        )
    except Exception as exc:
        result.update(list_status="error", list_error=describe_error(exc))
        return result

    try:
        if not items:
            result['detail_status'] = 'no_matching_items'
            if pages > 1 and next_url:
                result['more_pages'] = [validate_source(fetcher, (*spec[:4], next_url, *spec[5:]), pages-1)]
            return result
        detail_data, detail_mime, detail_url = fetcher.get(items[0]["url"], hosts, page_kind='detail', config=config)
        result.update(detail_http_status=fetcher.last_status, detail_initial_http_status=fetcher.initial_status, detail_fetch_mode=fetcher.last_mode)
        source = type("RegisteredSource", (), {
            "id": source_id,
            "name": name,
            "region": region,
            "kind": kind,
            "config": config,
        })()
        detail = parse_detail(detail_data, detail_url, items[0], source)
        result.update(
            detail_status="ok",
            detail_mime=detail_mime,
            detail_title=detail["title"],
            body_chars=len(detail["body"]),
            published=detail["published"],
            parsed_kind=detail["kind"],
            attachments=len(detail["attachments"]),
        )
    except Exception as exc:
        result.update(
            detail_status="error",
            detail_http_status=fetcher.last_status,
            detail_initial_http_status=fetcher.initial_status,
            detail_fetch_mode=fetcher.last_mode,
            detail_error=describe_error(exc),
        )
    if pages > 1 and next_url:
        result['more_pages'] = [validate_source(fetcher, (*spec[:4], next_url, *spec[5:]), pages-1)]
    return result


def validate_jiangsu_interpretation_filter(fetcher):
    """Count valid Jiangsu items separately from NHC reposts on the same page."""
    url = "https://wjw.jiangsu.gov.cn/col/col7292/index.html"
    hosts = ["wjw.jiangsu.gov.cn"]
    result = {"id": "js-interpretation-origin-audit", "url": url}
    try:
        data, _, final_url = fetcher.get(url, hosts)
        all_items, _ = parse_list(data, final_url, {
            "list_selector": "li",
            "hosts": hosts + ["www.nhc.gov.cn"],
        })
        items, _ = parse_list(data, final_url, {
            "list_selector": "li",
            "hosts": hosts + ["www.nhc.gov.cn"],
            "list_hosts": hosts,
        })
        origins = Counter(urlsplit(item["url"]).hostname for item in all_items)
        result.update(
            status="ok",
            total_item_count=len(all_items),
            link_origins=dict(origins),
            accepted_jiangsu_item_count=len(items),
            accepted_sample_title=items[0]["title"] if items else "",
            filtered_external_item_count=len(all_items) - len(items),
        )
    except Exception as exc:
        result.update(status="unverified", check_error=describe_error(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', choices=[s[0] for s in SPECS])
    parser.add_argument('--pages', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--output', type=Path, default=Path('evidence/sources/manifest.json'))
    args = parser.parse_args()
    with SafeFetcher(Settings(domain_delay_seconds=2, fetch_timeout=20)) as fetcher:
        checks = []
        for spec in SPECS:
            if not args.source or spec[0] in args.source:
                result = validate_source(fetcher, spec, args.pages)
                checks.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        report = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_checks": checks,
            "origin_filter_checks": [validate_jiangsu_interpretation_filter(fetcher)] if not args.source else [],
        }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
