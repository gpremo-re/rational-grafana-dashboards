#!/usr/bin/env python3
"""
Static builder for the `rrc-site-overview` Grafana dashboard.

Reproduces the dashboard exactly as it existed at the end of the 2026-04-30
authoring session (Claude Code session 58ca50f5-d1ea-4d25-8ed2-d8cb64eaa849),
which was previously API-imported into the running Grafana and lost when the
kube-prometheus-stack helm release was upgraded on 2026-05-04 (Grafana storage
was emptyDir, no persistence).

Run with no arguments. Output:
  dashboards/rrc-site-overview.json

A ConfigMap is generated from this JSON at apply time via
manifests/kustomization.yaml (configMapGenerator), so the JSON is the
single source of truth — no duplicated YAML to keep in sync.
"""
from __future__ import annotations
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD_OUT = REPO_ROOT / "dashboards" / "rrc-site-overview.json"

PROM = {"type": "prometheus", "uid": "prometheus"}
SITE = 'rrc_site="$site"'

# ---------- panel helpers ----------

def ts_panel(pid, title, x, y, w, h, queries, *, unit=None, stack=False, decimals=2):
    p = {
        "id": pid, "type": "timeseries", "title": title,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"refId": chr(65 + i), "datasource": PROM, "expr": q[0], "legendFormat": q[1]}
            for i, q in enumerate(queries)
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 10 if stack else 5,
                    "stacking": {"mode": "normal" if stack else "none"},
                },
                "decimals": decimals,
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom", "calcs": ["last", "max"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def stat_panel(pid, title, x, y, w, h, expr, *, unit=None, decimals=0, color_thresholds=None):
    p = {
        "id": pid, "type": "stat", "title": title,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": PROM, "expr": expr, "instant": True}],
        "fieldConfig": {"defaults": {"unit": unit or "none", "decimals": decimals}, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto", "colorMode": "value", "graphMode": "area",
        },
    }
    if color_thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": color_thresholds}
    return p


def gauge_panel(pid, title, x, y, w, h, expr, *, decimals=1):
    return {
        "id": pid, "type": "gauge", "title": title,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": PROM, "expr": expr, "instant": True}],
        "fieldConfig": {
            "defaults": {
                "unit": "percentunit", "min": 0, "max": 1, "decimals": decimals,
                "thresholds": {"mode": "absolute", "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 0.7},
                    {"color": "red", "value": 0.9},
                ]},
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "showThresholdLabels": False, "showThresholdMarkers": True},
    }


def table_panel(pid, title, x, y, w, h, expr):
    return {
        "id": pid, "type": "table", "title": title,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": PROM, "expr": expr, "instant": True, "format": "table"}],
        "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": []},
        "options": {"showHeader": True, "footer": {"show": False}},
        "transformations": [{"id": "organize", "options": {"excludeByName": {
            "Time": True, "__name__": True, "endpoint": True, "job": True,
            "service": True, "rrc_namespace": True, "rrc_site": True,
        }}}],
    }


# ---------- step 1: scaffold (idx 845) ----------

def build_scaffold():
    panels = []
    pid = [0]
    def nxt():
        pid[0] += 1
        return pid[0]

    # Row: Overview
    panels.append({"id": nxt(), "type": "row", "title": "Overview",
                   "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}, "collapsed": False, "panels": []})
    panels.append(stat_panel(nxt(), "Pods Up (total)", 0, 1, 4, 4,
        f"count(up{{{SITE}}} == 1)",
        color_thresholds=[{"color": "red", "value": None},
                          {"color": "yellow", "value": 1},
                          {"color": "green", "value": 2}]))
    panels.append(gauge_panel(nxt(), "Heap Utilization (site avg)", 4, 1, 5, 4,
        f'avg(jvm_memory_used_bytes{{{SITE}, area="heap"}}) '
        f'/ avg(jvm_memory_max_bytes{{{SITE}, area="heap"}})'))
    panels.append(stat_panel(nxt(), "Requests / sec", 9, 1, 5, 4,
        f'sum(rate(http_server_requests_seconds_count{{{SITE}, uri!="/actuator/prometheus"}}[5m]))',
        unit="reqps", decimals=1,
        color_thresholds=[{"color": "green", "value": None}]))
    panels.append(stat_panel(nxt(), "5xx / sec", 14, 1, 5, 4,
        f'sum(rate(http_server_requests_seconds_count{{{SITE}, status=~"5.."}}[5m]))',
        unit="reqps", decimals=2,
        color_thresholds=[{"color": "green", "value": None},
                          {"color": "yellow", "value": 0.1},
                          {"color": "red", "value": 1}]))
    panels.append(stat_panel(nxt(), "Hikari Active (sum)", 19, 1, 5, 4,
        f"sum(hikaricp_connections_active{{{SITE}}})",
        decimals=0,
        color_thresholds=[{"color": "green", "value": None}]))

    # Row: Per-Pod Health (the "Pods" table panel here is removed by the polystat swap step)
    panels.append({"id": nxt(), "type": "row", "title": "Per-Pod Health",
                   "gridPos": {"x": 0, "y": 5, "w": 24, "h": 1}, "collapsed": False, "panels": []})
    panels.append(table_panel(nxt(), "Pods", 0, 6, 24, 8,
        f'sum by (rrc_component, application, instance) (up{{{SITE}}})'))

    # Row: Memory & CPU
    panels.append({"id": nxt(), "type": "row", "title": "Memory & CPU",
                   "gridPos": {"x": 0, "y": 14, "w": 24, "h": 1}, "collapsed": False, "panels": []})
    panels.append(ts_panel(nxt(), "Heap Used (stacked by component)", 0, 15, 12, 8,
        [(f'sum by (rrc_component) (jvm_memory_used_bytes{{{SITE}, area="heap"}})', "{{rrc_component}}")],
        unit="bytes", stack=True))
    panels.append(ts_panel(nxt(), "Heap Utilization (per pod)", 12, 15, 12, 8,
        [(f'jvm_memory_used_bytes{{{SITE}, area="heap", id="G1 Old Gen"}} '
          f'/ on(instance) group_left jvm_memory_committed_bytes{{{SITE}, area="heap", id="G1 Old Gen"}}',
          "{{instance}}")],
        unit="percentunit"))
    panels.append(ts_panel(nxt(), "CPU Usage (per pod)", 0, 23, 12, 8,
        [(f"process_cpu_usage{{{SITE}}}", "{{instance}}")],
        unit="percentunit"))
    panels.append(ts_panel(nxt(), "Load Avg 1m (per pod)", 12, 23, 12, 8,
        [(f"system_load_average_1m{{{SITE}}}", "{{instance}}")],
        decimals=2))

    # Row: HTTP
    panels.append({"id": nxt(), "type": "row", "title": "HTTP",
                   "gridPos": {"x": 0, "y": 31, "w": 24, "h": 1}, "collapsed": False, "panels": []})
    panels.append(ts_panel(nxt(), "Requests / sec (by component)", 0, 32, 12, 8,
        [(f'sum by (rrc_component) (rate(http_server_requests_seconds_count{{{SITE}, uri!="/actuator/prometheus"}}[5m]))',
          "{{rrc_component}}")],
        unit="reqps", stack=True))
    panels.append(ts_panel(nxt(), "Requests / sec (per pod)", 12, 32, 12, 8,
        [(f'sum by (instance) (rate(http_server_requests_seconds_count{{{SITE}, uri!="/actuator/prometheus"}}[5m]))',
          "{{instance}}")],
        unit="reqps"))
    panels.append(ts_panel(nxt(), "5xx Rate (per pod)", 0, 40, 12, 8,
        [(f'sum by (instance) (rate(http_server_requests_seconds_count{{{SITE}, status=~"5.."}}[5m]))',
          "{{instance}}")],
        unit="reqps"))
    panels.append(ts_panel(nxt(), "Top URIs by Request Rate (top 10)", 12, 40, 12, 8,
        [(f'topk(10, sum by (uri) (rate(http_server_requests_seconds_count{{{SITE}, uri!="/actuator/prometheus"}}[5m])))',
          "{{uri}}")],
        unit="reqps"))

    # Row: Connections & GC
    panels.append({"id": nxt(), "type": "row", "title": "Connections & GC",
                   "gridPos": {"x": 0, "y": 48, "w": 24, "h": 1}, "collapsed": False, "panels": []})
    panels.append(ts_panel(nxt(), "Hikari Active Connections (per pod)", 0, 49, 12, 8,
        [(f"sum by (instance, pool) (hikaricp_connections_active{{{SITE}}})", "{{instance}} / {{pool}}")]))
    panels.append(ts_panel(nxt(), "GC Pressure (per pod)", 12, 49, 12, 8,
        [(f"sum by (instance) (rate(jvm_gc_pause_seconds_sum{{{SITE}}}[5m]))", "{{instance}}")],
        unit="percentunit", decimals=4))

    templating = {"list": [{
        "name": "site", "label": "Site", "type": "query",
        "datasource": PROM,
        "query": {"query": "label_values(up, rrc_site)", "refId": "siteVar"},
        "definition": "label_values(up, rrc_site)",
        "refresh": 1, "includeAll": False, "multi": False,
        "current": {}, "options": [], "regex": "",
        "skipUrlSync": False, "sort": 1,
    }]}

    # Initial links — replaced by mutate_links_to_explicit_url below.
    links = [{
        "title": "Per-pod deep dive (Spring Boot 3)",
        "type": "dashboards", "tags": [], "asDropdown": False,
        "icon": "external link", "includeVars": False, "keepTime": True,
        "targetBlank": False, "url": "/d/rrc-pod-details/rrc-pod-details",
    }]

    return {
        "title": "RRC Site Overview",
        "uid": "rrc-site-overview",
        "tags": ["rrc", "site", "overview"],
        "schemaVersion": 41,
        "version": 0,
        "refresh": "30s",
        "time": {"from": "now-1h", "to": "now"},
        "timepicker": {},
        "templating": templating,
        "panels": panels,
        "links": links,
        "editable": True,
        "graphTooltip": 1,
        "style": "dark",
        "fiscalYearStartMonth": 0,
    }


# ---------- mutation steps (in chronological order) ----------

def mutate_links_to_explicit_url(dash):
    """idx 869: replace `links[*].type=dashboards` with explicit `type=link` to a single drill-down."""
    dash["links"] = [{
        "title": "Per-pod deep dive (RRC Pod Details)",
        "type": "link", "icon": "external link",
        "url": "/d/rrc-pod-details/rrc-pod-details",
        "targetBlank": False, "keepTime": True, "includeVars": True,
        "asDropdown": False, "tooltip": "", "tags": [],
    }]


def mutate_swap_pods_for_polystat(dash):
    """idx 886: drop "Pods" table; insert a polystat hex grid right after the Per-Pod Health row."""
    polystat = {
        "type": "grafana-polystat-panel",
        "title": "Pod Health (heap % | down=red)",
        "datasource": PROM,
        "gridPos": {"x": 0, "y": 6, "w": 24, "h": 8},
        "targets": [{
            "refId": "A", "datasource": PROM,
            "expr": (
                '('
                '  100 * sum by (instance) (jvm_memory_used_bytes{rrc_site="$site", area="heap"})'
                '       / sum by (instance) (jvm_memory_committed_bytes{rrc_site="$site", area="heap"})'
                ')'
                ' or '
                '('
                '  999 * sum by (instance) (up{rrc_site="$site"} == bool 0)'
                ')'
            ),
            "legendFormat": "{{instance}}", "instant": True,
        }],
        "fieldConfig": {
            "defaults": {
                "unit": "percent", "decimals": 1,
                "thresholds": {"mode": "absolute", "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 70},
                    {"color": "red", "value": 90},
                ]},
            },
            "overrides": [],
        },
        "options": {
            "globalAutoScaleFonts": True,
            "globalDisplayMode": "all",
            "globalDisplayTextTriggeredEmpty": "OK",
            "globalGradientsEnabled": True,
            "globalPolygonBorderColor": "black",
            "globalPolygonBorderSize": 2,
            "globalRegexPattern": "",
            "globalShape": "hexagon_pointed_top",
            "globalTextFontAutoColor": True,
            "globalTextFontFamily": "Roboto",
            "globalTooltipsEnabled": True,
            "globalTooltipsFontFamily": "Roboto",
            "globalTooltipsFontSize": 12,
            "globalUnitFormat": "percent",
            "panelTitle": "Pod Health",
            "polystat": {"rows": -1, "columns": -1, "globalShape": "hexagon_pointed_top"},
        },
        "pluginVersion": "2.2.0",
    }

    # Drop existing "Pods" panel(s)
    dash["panels"] = [p for p in dash["panels"] if p.get("title") != "Pods"]

    # Allocate a new id
    existing_ids = [p.get("id") for p in dash["panels"] if isinstance(p.get("id"), int)]
    polystat["id"] = max(existing_ids) + 1

    # Insert after the Per-Pod Health row
    row_idx = next(i for i, p in enumerate(dash["panels"])
                   if p.get("title") == "Per-Pod Health" and p.get("type") == "row")
    dash["panels"].insert(row_idx + 1, polystat)


def _polystat(dash):
    return next(p for p in dash["panels"] if p.get("title", "").startswith("Pod Health"))


def mutate_polystat_query_down_first(dash):
    """idx 903: reorder the heap-vs-down `or` so the down-pod sentinel is on the LHS."""
    p = _polystat(dash)
    p["targets"][0]["expr"] = (
        '('
        '  999 * sum by (instance) (up{rrc_site="$site"} == 0)'
        ')'
        ' or '
        '('
        '  100 * sum by (instance) (jvm_memory_used_bytes{rrc_site="$site", area="heap"})'
        '       / sum by (instance) (jvm_memory_committed_bytes{rrc_site="$site", area="heap"})'
        ')'
    )


def mutate_polystat_thresholds_v1(dash):
    """idx 925: set polystat-native thresholds + decimals + disable gradients."""
    p = _polystat(dash)
    p["options"]["globalThresholdsConfig"] = [
        {"color": "#299c46",                 "state": 0, "value": 0},
        {"color": "rgba(237, 129, 40, 0.89)", "state": 1, "value": 70},
        {"color": "#d44a3a",                 "state": 2, "value": 90},
    ]
    p["options"]["globalDecimals"] = 1
    p["options"]["globalGradientsEnabled"] = False


def mutate_polystat_query_to_gc_overhead(dash):
    """idx 952: pivot signal from heap % to GC pause-time fraction; rescale thresholds."""
    p = _polystat(dash)
    p["targets"][0]["expr"] = (
        '( 999 * sum by (instance) (up{rrc_site="$site"} == 0) )'
        ' or '
        '( 100 * sum by (instance) (rate(jvm_gc_pause_seconds_sum{rrc_site="$site"}[5m])) )'
    )
    p["title"] = "Pod Health (GC overhead %, down=red)"
    p["options"]["globalThresholdsConfig"] = [
        {"color": "#299c46",                 "state": 0, "value": 0},
        {"color": "rgba(237, 129, 40, 0.89)", "state": 1, "value": 2},
        {"color": "#d44a3a",                 "state": 2, "value": 10},
    ]
    p["options"]["globalDecimals"] = 2


def mutate_polystat_query_to_worst_of_three(dash):
    """idx 966: composite worst-of-3 — GC overhead, 5xx*2, blocked-thread frac*2."""
    p = _polystat(dash)
    p["targets"][0]["expr"] = (
        '( 999 * sum by (instance) (up{rrc_site="$site"} == 0) )\n'
        'or\n'
        'max by (instance) (\n'
        '  (\n'
        '    sum by (instance) (rate(jvm_gc_pause_seconds_sum{rrc_site="$site"}[5m])) * 100\n'
        '  )\n'
        '  or\n'
        '  (\n'
        '    100 *\n'
        '    sum by (instance) (rate(http_server_requests_seconds_count{rrc_site="$site", status=~"5.."}[5m]))\n'
        '    /\n'
        '    sum by (instance) (rate(http_server_requests_seconds_count{rrc_site="$site"}[5m])) * 2\n'
        '  )\n'
        '  or\n'
        '  (\n'
        '    100 *\n'
        '    sum by (instance) (jvm_threads_states_threads{rrc_site="$site", state="blocked"})\n'
        '    /\n'
        '    sum by (instance) (jvm_threads_live_threads{rrc_site="$site"}) * 2\n'
        '  )\n'
        ')'
    )
    p["title"] = "Pod Health (worst-of: GC, 5xx, blocked threads | down=red)"


def mutate_polystat_label_replace_to_pod_short(dash):
    """idx 979: wrap composite in label_replace to expose `pod_short`; show name on hexes."""
    p = _polystat(dash)
    inner = (
        '( 999 * sum by (instance) (up{rrc_site="$site"} == 0) ) or '
        'max by (instance) ('
        '  ( sum by (instance) (rate(jvm_gc_pause_seconds_sum{rrc_site="$site"}[5m])) * 100 )'
        '  or '
        '  ( 100 * sum by (instance) (rate(http_server_requests_seconds_count{rrc_site="$site", status=~"5.."}[5m])) '
        '         / sum by (instance) (rate(http_server_requests_seconds_count{rrc_site="$site"}[5m])) * 2 )'
        '  or '
        '  ( 100 * sum by (instance) (jvm_threads_states_threads{rrc_site="$site", state="blocked"}) '
        '         / sum by (instance) (jvm_threads_live_threads{rrc_site="$site"}) * 2 )'
        ')'
    )
    p["targets"][0]["expr"] = (
        'label_replace(' + inner +
        ', "pod_short", "$1-$2"'
        ', "instance", "devops-[^-]+-([^-]+)-[^-]+-([^-]+)")'
    )
    p["targets"][0]["legendFormat"] = "{{pod_short}}"
    p["options"]["globalDisplayMode"] = "name"


def mutate_polystat_display_iterations(dash):
    """idx 992 → 995 → 1004: cycled globalDisplayMode through 'all' → 'nameOnly' → 'all'.
    Net effect: globalDisplayMode = 'all' (the final API-set value).
    Then the user toggled the value-hide via the Grafana UI; the actual key the UI
    persisted is `globalShowValueEnabled: False` (recorded in the lessons-learned
    note 2026-04-30-lesson-grafana-polystat-config). We set both here to match
    the final saved state.
    """
    p = _polystat(dash)
    p["options"]["globalDisplayMode"] = "all"
    p["options"]["globalShowValueEnabled"] = False


def mutate_polystat_description(dash):
    """idx 1026: long markdown description on the Pod Health panel."""
    p = _polystat(dash)
    p["description"] = (
        "Worst-of-3 health score per pod. Each signal is scaled so its red threshold lands at 10:\n"
        "\n"
        "- **GC pause-time fraction** — `rate(jvm_gc_pause_seconds_sum[5m]) * 100`. "
        "The fraction of wallclock the JVM is stop-the-world paused. Red at 10%.\n"
        "- **HTTP 5xx rate** — `rate(5xx) / rate(total) * 200`. "
        "Fraction of requests returning 5xx. Red at 5%.\n"
        "- **Blocked thread fraction** — "
        "`jvm_threads_states_threads{state=\"blocked\"} / jvm_threads_live_threads * 200`. "
        "Red at 5%.\n"
        "\n"
        "**Color**: green <2 | yellow 2–10 | red ≥10.\n"
        "\n"
        "**Down pods** (`up == 0`) bypass the composite and score 999 → red immediately, "
        "without waiting for the Prometheus 5-min staleness window.\n"
        "\n"
        "**Why GC over heap %?** G1GC triggers concurrent collection at IHOP (45% of total heap by default), "
        "so Old Gen at 70–80% in steady state is normal on G1 — a heap-utilization dot would be permanently "
        "yellow on a healthy app. GC pause-time is collector-agnostic and directly measures user-visible latency.\n"
        "\n"
        "**Known blind spots**: container OOMKill from native-memory growth (off-heap, code cache, direct buffers) "
        "is invisible to JVM heap and GC metrics — would need `container_memory_working_set_bytes / limit` as a "
        "separate dot. Tomcat thread-pool saturation isn't emitted by these apps (`tomcat_threads_*` returns no series), "
        "so we use `jvm_threads_states_threads{state=\"blocked\"}` as the proxy for thread saturation."
    )


# ---------- compose ----------

MUTATIONS = [
    mutate_links_to_explicit_url,
    mutate_swap_pods_for_polystat,
    mutate_polystat_query_down_first,
    mutate_polystat_thresholds_v1,
    mutate_polystat_query_to_gc_overhead,
    mutate_polystat_query_to_worst_of_three,
    mutate_polystat_label_replace_to_pod_short,
    mutate_polystat_display_iterations,
    mutate_polystat_description,
]


def build_dashboard():
    dash = build_scaffold()
    for step in MUTATIONS:
        step(dash)
    return dash


def main():
    dash = build_dashboard()
    DASHBOARD_OUT.parent.mkdir(parents=True, exist_ok=True)

    dash_json = json.dumps(dash, indent=2, ensure_ascii=False)
    DASHBOARD_OUT.write_text(dash_json + "\n", encoding="utf-8")

    panels = [p for p in dash["panels"] if p.get("type") != "row"]
    rows = [p for p in dash["panels"] if p.get("type") == "row"]
    print(f"wrote {DASHBOARD_OUT.relative_to(REPO_ROOT)} ({len(rows)} rows, {len(panels)} panels)")


if __name__ == "__main__":
    main()
