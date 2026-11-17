"""Read-only live validation of registered policy source adapters."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from policy_v2.network import SafeFetcher
from policy_v2.parsing import parse_detail, parse_list
from policy_v2.settings import Settings
from policy_v2.sources import COMMON_BODY, SPECS


def describe_error(exc):
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
    return f"{type(current).__name__}:{str(current)[:240]}"


def validate_source(fetcher, spec):
    source_id, name, region, kind, url, adapter, selector, hosts = spec
    config = {
        "adapter": adapter,
        "list_selector": selector,
        "body_selectors": COMMON_BODY,
        "hosts": hosts,
        "list_hosts": [urlsplit(url).hostname],
        "max_pages": 3,
    }
    result = {"id": source_id, "url": url}
    try:
        data, mime, final_url = fetcher.get(url, hosts)
        result.update(http_status=200, mime=mime, bytes=len(data), final_url=final_url)
    except Exception as exc:
        result.update(http_status="error", fetch_error=describe_error(exc))
        return result

    try:
        items, next_url = parse_list(data, final_url, config)
        result.update(
            list_status="ok",
            item_count=len(items),
            sample_title=items[0]["title"],
            sample_url=items[0]["url"],
            next_page=next_url,
        )
    except Exception as exc:
        result.update(list_status="error", list_error=describe_error(exc))
        return result

    try:
        detail_data, detail_mime, detail_url = fetcher.get(items[0]["url"], hosts)
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
        result.update(detail_status="error", detail_error=describe_error(exc))
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
    fetcher = SafeFetcher(Settings(domain_delay_seconds=2, fetch_timeout=20))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_checks": [validate_source(fetcher, spec) for spec in SPECS],
        "origin_filter_checks": [validate_jiangsu_interpretation_filter(fetcher)],
    }
    output = Path("evidence/sources/manifest.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
