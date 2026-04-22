# TraffiCure Database Schema Guide — Complete AI Reference

> **Purpose**: This document is the single source of truth for the TraffiCure PostgreSQL database. It is designed so that an AI agent can answer any data question, write any query, and understand every relationship without needing access to the live schema. No interpretation required — everything is explicit.
>
> **Database**: PostgreSQL with PostGIS extension
> **Schemas**: `public`, `road_hierarchy`
> **Last Updated**: 2026-04-10

---

## Table of Contents

1. [Schema Overview & Entity Relationship Tree](#1-schema-overview--entity-relationship-tree)
2. [Enum / Allowed Values Reference](#2-enum--allowed-values-reference)
3. [Schema: `public` — Core Traffic Tables](#3-schema-public--core-traffic-tables)
4. [Schema: `road_hierarchy` — Geographic Hierarchy Tables](#4-schema-road_hierarchy--geographic-hierarchy-tables)
5. [Views](#5-views)
6. [Helper Functions](#6-helper-functions)
7. [Cross-Schema FK Bridge](#7-cross-schema-fk-bridge)
8. [time_bucket_15m Encoding](#8-time_bucket_15m-encoding)
9. [Common Query Patterns](#9-common-query-patterns)
10. [Backup / Legacy Tables (Ignore)](#10-backup--legacy-tables-ignore)

---

## 1. Schema Overview & Entity Relationship Tree

### 1.1 `public` Schema — Core Traffic Data

```
public.cities (PK: city_id)
 │
 ├── public.network_hourly_snapshot (PK: organization_id + snapshot_date + hour_of_day)
 │    └── Network-wide hourly aggregates (speeds, congestion_km, coverage)
 │
 ├── public.area_hourly_metrics (PK: grid_type + grid_cell_id + bucket_hour) ── partitioned by grid_type
 │    └── Hourly metrics per spatial grid cell (locality/pincode/h3/geohash)
 │
 └── public.road_segment (PK: road_id, tag = city grouping)
      │
      ├── public.realtime_road_status (PK: road_id) ──── 1:1 latest snapshot
      │
      ├── public.road_freeflow_profile (PK: road_id) ──── 1:1 baseline freeflow speed/travel time
      │
      ├── public.alert (PK: alert_id, FK: road_id)
      │    │
      │    └── public.traffic_alert_lifecycle_log (PK: event_id, FK: alert_id, FK: road_id)
      │
      ├── public.analytics_hourly_road_metrics (PK: road_id + bucket_start_time)
      │
      └── public.analytics_hourly_corridor_metrics (PK: corridor_id + bucket_start_time)
           └── Hourly aggregates per corridor (speeds, delays, segment breakdown)
```

### 1.2 `road_hierarchy` Schema — Geographic Hierarchy

```
public.cities (city_id)
 │
 ├── road_hierarchy.zone (PK: zone_id, FK: city_id → public.cities)
 │    │
 │    └── road_hierarchy.corridor_zone_map (PK: corridor_id + zone_id)
 │         │
 │         └── road_hierarchy.corridor (PK: corridor_id, FK: city_id → public.cities)
 │              │
 │              └── road_hierarchy.road_corridor_map (PK: road_master_id + corridor_id)
 │                   │
 │                   └── road_hierarchy.road_master (PK: road_master_id, UK: norm_name)
 │
 ├── road_hierarchy.division (PK: division_id, FK: city_id → public.cities)
 │
 ├── road_hierarchy.locality (PK: locality_id, FK: city_id → public.cities)
 │
 ├── road_hierarchy.sub_locality (PK: sub_locality_id, FK: city_id → public.cities)
 │
 └── road_hierarchy.postal_code (PK: postal_code_id, UK: postal_code)

public.road_segment (road_id)
 │
 ├── road_hierarchy.segment_hierarchy (PK: segment_id = road_id) ── denormalized flat row
 │
 ├── road_hierarchy.segment_road_map (PK: segment_id, FK: road_master_id)
 │
 ├── road_hierarchy.segment_division_map (PK: segment_id, FK: division_id)
 │
 ├── road_hierarchy.segment_local_map (PK: segment_id, FK: locality_id, sub_locality_id, postal_code_id)
 │
 ├── road_hierarchy.segment_junction_map (PK: junction_id + segment_id)
 │    │
 │    └── road_hierarchy.junction (PK: junction_id, FK: city_id → public.cities)
 │         └── Intersection points with PostGIS location
 │
 ├── road_hierarchy.road_grid_mapping (PK: road_id + grid_type + grid_cell_id)
 │    └── Maps roads to spatial grid cells (locality/pincode/h3/geohash) with overlap fraction
 │
 └── road_hierarchy.geocode_dump (PK: id, UK: segment_id) ── raw geocode API responses
```

### 1.3 Geographic Hierarchy Levels (Top → Bottom)

```
City → Zone → Corridor → Road Master → Road Segment (individual monitored link)
City → Division (administrative boundary, parallel to zone)
City → Locality → Sub-Locality → Postal Code (address-based, linked to segments)
```

---

## 2. Enum / Allowed Values Reference

These are the **actual distinct values** observed in production data:

| Column | Table(s) | Allowed Values |
|--------|----------|---------------|
| `traffic_status` | `realtime_road_status` | `NORMAL`, `SLOW`, `TRAFFIC_JAM` |
| `current_status` | `alert` | `ACTIVE`, `RESOLVED` |
| `alert_type` | `alert`, `traffic_alert_lifecycle_log` | `CONGESTION`, `RAPID_DETERIORATION` |
| `event_action` | `traffic_alert_lifecycle_log` | `CREATED`, `UPDATED`, `ESCALATED`, `RECOVERING`, `RESOLVED` |
| `severity` | `traffic_alert_lifecycle_log` | `WARNING`, `CRITICAL`, `NULL` (null = not yet classified) |
| `tag` | `road_segment` | City/area tags: `Kolkata`, `Pune`, `Howrah`, `Barrackpore`, `Bidhan Nagar`, etc. |
| `grid_type` | `area_hourly_metrics`, `road_grid_mapping` | `locality`, `pincode`, `h3`, `geohash` |
| `direction` | `segment_junction_map` | `N`, `S`, `E`, `W`, `NE`, `NW`, `SE`, `SW` |

---

## 3. Schema: `public` — Core Traffic Tables

### 3.1 `public.road_segment`

> **Purpose**: The master registry of all monitored road segments. Every traffic table references this via `road_id`. This is the **central entity** of the entire system.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_id` | `varchar(100)` | NO | — | **PK**. Unique segment identifier (e.g., TomTom segment ID). Format: alphanumeric string. |
| `road_name` | `varchar(255)` | YES | — | Human-readable name of the road segment (e.g., "NH 16 - Kolkata to Burdwan") |
| `road_length_meters` | `integer` | NO | — | Physical length of the segment in meters |
| `geometry` | `geometry` (PostGIS) | YES | — | LineString geometry representing the road segment path (SRID 4326) |
| `created_at` | `timestamp` | NO | `CURRENT_TIMESTAMP` | Row creation time |
| `tag` | `varchar(100)` | YES | — | City/area grouping tag. See [Enum Reference](#2-enum--allowed-values-reference) |
| `organization_id` | `varchar(100)` | YES | — | Tenant/organization identifier for multi-tenancy |
| `display_point` | `geometry` (PostGIS) | YES | — | A single lat/lng point for map label placement |
| `metadata` | `jsonb` | YES | — | Flexible JSON metadata (indexed with GIN) |

**Primary Key**: `road_id`
**Indexes**: `road_id`, `tag`, `organization_id`, `metadata` (GIN)
**Referenced by**: `realtime_road_status`, `alert`, `traffic_alert_lifecycle_log`, `analytics_hourly_road_metrics` (implicit), all `road_hierarchy.segment_*` maps

---

### 3.2 `public.realtime_road_status`

> **Purpose**: Holds the **latest single snapshot** of traffic conditions per road segment. Updated continuously — always exactly 1 row per road. This is the go-to table for "what's happening right now" queries.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_id` | `varchar(100)` | NO | — | **PK** + **FK** → `road_segment.road_id`. One row per segment. |
| `current_speed_kmph` | `double` | YES | — | Latest observed speed in km/h |
| `current_travel_time_sec` | `integer` | YES | — | Current travel time through the segment in seconds |
| `freeflow_travel_time_sec` | `integer` | YES | — | Travel time under free-flow (no traffic) conditions in seconds |
| `delay_percent` | `double` | YES | — | `((current - freeflow) / freeflow) * 100`. Percentage delay over freeflow |
| `traffic_status` | `varchar(20)` | YES | — | Categorical status. Values: `NORMAL`, `SLOW`, `TRAFFIC_JAM` |
| `traffic_event_time` | `timestamp` | YES | — | When the traffic data was observed by the source provider |
| `saturation_index` | `double` | YES | — | Ratio of current travel time to baseline median (higher = worse). `current_tt / baseline_median_tt` |
| `deviation_index` | `double` | YES | — | How far current conditions deviate from historical baseline |
| `velocity_decay` | `double` | YES | — | Rate of speed decrease: `1 - (current_speed / freeflow_speed)` |
| `impact_cost_sec` | `integer` | YES | — | Additional seconds of delay compared to baseline |
| `persistence_count` | `integer` | YES | — | Number of consecutive observations where congestion persisted |
| `time_bucket_15m` | `integer` | YES | — | Encoded 15-min time slot. See [Section 8](#8-time_bucket_15m-encoding) |
| `updated_at` | `timestamp` | NO | `CURRENT_TIMESTAMP` | Last update timestamp |
| `speed_ratio` | `double` | YES | — | `current_speed / freeflow_speed` (0-1 range, lower = worse) |
| `delay_intensity_sec_per_km` | `double` | YES | — | Delay normalized per kilometer of road length |

**Primary Key**: `road_id` (1:1 with road_segment)
**Foreign Key**: `road_id` → `road_segment.road_id`
**Indexes**: `road_id`, `traffic_event_time`, `time_bucket_15m`

---

### 3.3 `public.alert`

> **Purpose**: Active and resolved traffic alerts. An alert is created when congestion or rapid deterioration is detected on a road segment. Each alert has a lifecycle tracked in `traffic_alert_lifecycle_log`.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `alert_id` | `bigint` | NO | `nextval(seq)` | **PK**. Auto-incrementing unique alert ID. |
| `road_id` | `varchar(100)` | NO | — | **FK** → `road_segment.road_id` |
| `alert_type` | `varchar(50)` | NO | — | `CONGESTION` or `RAPID_DETERIORATION` |
| `current_status` | `varchar(20)` | NO | `'ACTIVE'` | `ACTIVE` or `RESOLVED` |
| `alert_event_time` | `timestamp` | NO | — | When the alert condition was first detected |
| `updated_at` | `timestamp` | NO | `CURRENT_TIMESTAMP` | Last status change |
| `resolved_at` | `timestamp` | YES | — | When alert was resolved (NULL if still active) |
| `metadata` | `jsonb` | YES | — | Additional alert context (thresholds, trigger values, etc.) |
| `created_at` | `timestamp` | NO | `CURRENT_TIMESTAMP` | Row creation time |

**Primary Key**: `alert_id`
**Foreign Key**: `road_id` → `road_segment.road_id`
**Indexes**: `alert_id`, `road_id`, `alert_type`, `current_status`, `(road_id, current_status)`, `alert_event_time`, `created_at`, `updated_at`

---

### 3.4 `public.traffic_alert_lifecycle_log`

> **Purpose**: Immutable audit log of every state change for every alert. Tracks the full lifecycle: CREATED → UPDATED → ESCALATED → RECOVERING → RESOLVED. Each row captures a metrics snapshot at the time of the event.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_id` | `bigint` | NO | `nextval(seq)` | **PK**. Auto-incrementing. |
| `alert_id` | `bigint` | NO | — | **FK** → `alert.alert_id` |
| `road_id` | `varchar(100)` | NO | — | **FK** → `road_segment.road_id` |
| `alert_type` | `varchar(50)` | YES | — | `CONGESTION` or `RAPID_DETERIORATION` |
| `event_action` | `varchar(20)` | NO | — | `CREATED`, `UPDATED`, `ESCALATED`, `RECOVERING`, `RESOLVED` |
| `severity` | `varchar(20)` | YES | — | `WARNING`, `CRITICAL`, or NULL |
| `metrics_snapshot` | `jsonb` | NO | — | Full metrics state at the time of this event (congestion_score, speed, delays, etc.) |
| `reason` | `text` | YES | — | Human-readable reason for the state transition |
| `suppression_reason` | `varchar(100)` | YES | — | If the alert was suppressed, why (e.g., "below threshold") |
| `observation_id` | `bigint` | YES | — | Reference to the triggering observation |
| `metric_id` | `bigint` | YES | — | Reference to the triggering metric |
| `created_at` | `timestamp` | NO | `CURRENT_TIMESTAMP` | When this log entry was created |
| `alert_event_time` | `timestamp` | NO | — | The traffic event time that triggered this lifecycle event |

**Primary Key**: `event_id`
**Foreign Keys**: `alert_id` → `alert.alert_id`, `road_id` → `road_segment.road_id`
**Indexes**: `event_id`, `alert_id`, `road_id`, `event_action`, `(alert_id, event_action)`, `(road_id, event_action)`, `alert_event_time`, `created_at`, `observation_id`, `metric_id`

---

### 3.5 `public.analytics_hourly_road_metrics`

> **Purpose**: Pre-aggregated hourly analytics per road. Used for dashboards and historical trend analysis. Contains averages, min/max, percentiles, and reliability metrics.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_id` | `varchar(100)` | NO | — | **PK (part 1)**. Road segment ID |
| `bucket_start_time` | `timestamp` | NO | — | **PK (part 2)**. Start of the hour bucket |
| `day_of_week` | `smallint` | YES | — | 0=Sunday, 1=Monday, …, 6=Saturday |
| `hour_of_day` | `smallint` | YES | — | 0–23 |
| `avg_current_travel_time_sec` | `double` | YES | — | Average observed travel time in the hour |
| `avg_freeflow_travel_time_sec` | `double` | YES | — | Average freeflow travel time |
| `avg_typical_travel_time_sec` | `double` | YES | — | Average typical (baseline) travel time |
| `avg_speed_kmph` | `double` | YES | — | Average speed in the hour |
| `avg_typical_speed_kmph` | `double` | YES | — | Average typical speed |
| `avg_freeflow_speed_kmph` | `double` | YES | — | Average freeflow speed |
| `min_speed_kmph` | `double` | YES | — | Minimum speed in the hour |
| `max_speed_kmph` | `double` | YES | — | Maximum speed in the hour |
| `avg_delay_pct` | `double` | YES | — | Average delay percentage |
| `avg_delay_seconds` | `integer` | YES | — | Average delay in seconds |
| `avg_delay_intensity` | `double` | YES | — | Average delay per km |
| `stddev_speed` | `double` | YES | — | Standard deviation of speed (reliability indicator) |
| `coeff_variation` | `double` | YES | — | Coefficient of variation for speed |
| `p95_travel_time_sec` | `double` | YES | — | 95th percentile travel time (worst-case planning metric) |
| `sample_count` | `integer` | YES | — | Number of observations in this hour |
| `updated_at` | `timestamp` | YES | `CURRENT_TIMESTAMP` | — |

**Primary Key**: `(road_id, bucket_start_time)`
**Indexes**: `(road_id, bucket_start_time)`, `(bucket_start_time, hour_of_day)`, `bucket_start_time`, covering index on `(road_id, bucket_start_time, hour_of_day) INCLUDE (avg_speed_kmph, avg_freeflow_speed_kmph, avg_delay_pct)`

---

### 3.6 `public.road_freeflow_profile`

> **Purpose**: Baseline free-flow speed and travel time per road segment, computed from night-time samples when traffic is minimal. Used as the reference for delay calculations. One row per road (1:1 with `road_segment`).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_id` | `varchar(100)` | NO | — | **PK** + implicit FK → `road_segment.road_id` |
| `freeflow_travel_time_sec` | `double` | YES | — | Travel time in seconds under free-flow conditions |
| `freeflow_speed_kmph` | `double` | YES | — | Speed in km/h under free-flow conditions |
| `night_sample_count` | `integer` | YES | — | Number of night-time observations used to compute the profile |
| `observation_window_start` | `date` | YES | — | Start of the data window used for computation |
| `observation_window_end` | `date` | YES | — | End of the data window used for computation |
| `computed_at` | `timestamp` | YES | `CURRENT_TIMESTAMP` | When this profile was last computed |

**Primary Key**: `road_id`
**Indexes**: `road_id`

---

### 3.7 `public.network_hourly_snapshot`

> **Purpose**: Hourly network-wide traffic summary per organization. Aggregates all road segments into a single row per org/date/hour for city-level dashboards and trend analysis.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `organization_id` | `varchar(100)` | NO | — | **PK (part 1)**. Organization/tenant ID |
| `snapshot_date` | `date` | NO | — | **PK (part 2)**. Date of the snapshot |
| `hour_of_day` | `smallint` | NO | — | **PK (part 3)**. 0–23 |
| `day_of_week` | `smallint` | NO | — | 0=Sunday … 6=Saturday |
| `network_tt_sec` | `double` | NO | — | Total travel time across the network in seconds |
| `network_freeflow_tt_sec` | `double` | NO | — | Total freeflow travel time (must be > 0) |
| `network_typical_tt_sec` | `double` | YES | — | Total typical (historical baseline) travel time |
| `network_speed_kmph` | `double` | NO | — | Average network speed |
| `network_freeflow_speed_kmph` | `double` | NO | — | Average freeflow speed |
| `network_typical_speed_kmph` | `double` | YES | — | Average typical speed |
| `congested_km` | `double` | NO | — | Total km of congested roads (≥ 0) |
| `total_network_length_km` | `double` | NO | — | Total monitored network length in km |
| `segment_count` | `integer` | NO | — | Number of road segments in the snapshot |
| `data_coverage_pct` | `double` | NO | — | Data coverage percentage (0–100) |
| `created_at` | `timestamptz` | NO | `now()` | — |

**Primary Key**: `(organization_id, snapshot_date, hour_of_day)`
**Check Constraints**: `hour_of_day` 0–23, `day_of_week` 0–6, `congested_km` ≥ 0, `network_freeflow_tt_sec` > 0, `data_coverage_pct` 0–100
**Indexes**: `(org, date DESC, hour) INCLUDE (speed metrics)`, `(org, hour, dow, date DESC) INCLUDE (tt, coverage)`, `(org, date DESC, hour) INCLUDE (congested_km, total_length)`

---

### 3.8 `public.area_hourly_metrics` (Partitioned)

> **Purpose**: Hourly traffic metrics per spatial grid cell. Partitioned by `grid_type` into 4 partitions: `locality`, `pincode`, `h3`, `geohash`. Used for heatmaps, area-level dashboards, and spatial congestion analysis. Includes both typical-baseline and freeflow-baseline delay calculations.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `grid_type` | `varchar(20)` | NO | — | **PK (part 1)** + **Partition key**. Values: `locality`, `pincode`, `h3`, `geohash` |
| `grid_cell_id` | `varchar(64)` | NO | — | **PK (part 2)**. Cell identifier (locality name, pincode, H3 index, or geohash) |
| `bucket_hour` | `timestamptz` | NO | — | **PK (part 3)**. Start of the hour bucket |
| `resolution` | `smallint` | YES | — | Grid resolution. NULL for locality/pincode; required for h3 (1–15) and geohash (1–12) |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `day_of_week` | `smallint` | YES | — | 0–6 |
| `hour_of_day` | `smallint` | YES | — | 0–23 |
| `avg_speed_kmph` | `double` | YES | — | Average speed across roads in this cell |
| `min_speed_kmph` | `double` | YES | — | Minimum speed |
| `max_speed_kmph` | `double` | YES | — | Maximum speed |
| `avg_freeflow_speed` | `double` | YES | — | Average freeflow speed |
| `avg_typical_speed` | `double` | YES | — | Average typical (baseline) speed |
| `avg_delay_pct` | `double` | YES | — | Average delay % (vs typical baseline) |
| `avg_delay_seconds` | `integer` | YES | — | Average delay in seconds (vs typical) |
| `total_delay_seconds` | `bigint` | YES | — | Total delay across all roads in cell |
| `avg_delay_intensity` | `double` | YES | — | Average delay per km |
| `congestion_pct` | `double` | YES | — | Percentage of roads congested (0–100) |
| `congestion_threshold_pct` | `double` | NO | `10.0` | Threshold used to determine congestion (> 0 and ≤ 100) |
| `avg_travel_time_index` | `double` | YES | — | Avg travel time index (current / freeflow) |
| `p95_travel_time_ratio` | `double` | YES | — | 95th percentile travel time ratio |
| `road_count` | `integer` | YES | — | Number of roads in this cell |
| `total_road_length_m` | `integer` | YES | — | Total road length in cell (meters) |
| `sample_count` | `integer` | YES | — | Number of observations |
| `active_alerts` | `integer` | NO | `0` | Currently active alerts in cell |
| `new_alerts` | `integer` | NO | `0` | New alerts in this hour |
| `resolved_alerts` | `integer` | NO | `0` | Resolved alerts in this hour |
| `updated_at` | `timestamptz` | NO | `now()` | — |
| `avg_delay_pct_ff` | `double` | YES | — | Average delay % (vs freeflow baseline) |
| `avg_delay_seconds_ff` | `integer` | YES | — | Average delay in seconds (vs freeflow) |

**Primary Key**: `(grid_type, grid_cell_id, bucket_hour)`
**Partition Key**: `LIST (grid_type)` — 4 partitions: `area_hourly_metrics_geohash`, `_h3`, `_locality`, `_pincode`
**Foreign Key**: `city_id` → `public.cities.city_id`
**Check Constraints**: `grid_type` in (locality, pincode, h3, geohash), `congestion_pct` 0–100, `hour_of_day` 0–23, `day_of_week` 0–6, resolution must be NULL for locality/pincode and NOT NULL for h3/geohash
**Indexes**: `(grid_cell_id, bucket_hour DESC)`, `(city_id, grid_type, bucket_hour DESC)`, `(grid_type, bucket_hour DESC)`, `(grid_type, resolution, bucket_hour DESC)`, congestion/delay/speed ranking indexes

---

### 3.9 `public.analytics_hourly_corridor_metrics`

> **Purpose**: Hourly aggregated traffic metrics per corridor. Used for corridor-level dashboards, travel time reliability, and congestion breakdown. Contains segment-level status counts (congested/slow/freeflow).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `corridor_id` | `varchar` | NO | — | **PK (part 1)**. References corridor in road_hierarchy |
| `bucket_start_time` | `timestamp` | NO | — | **PK (part 2)**. Start of the hour bucket |
| `day_of_week` | `smallint` | YES | — | 0–6 |
| `hour_of_day` | `smallint` | YES | — | 0–23 |
| `avg_speed_kmph` | `double` | YES | — | Average speed across corridor segments |
| `avg_typical_speed_kmph` | `double` | YES | — | Average typical speed |
| `avg_freeflow_speed_kmph` | `double` | YES | — | Average freeflow speed |
| `min_speed_kmph` | `double` | YES | — | Minimum speed in corridor |
| `max_speed_kmph` | `double` | YES | — | Maximum speed in corridor |
| `stddev_speed` | `double` | YES | — | Speed standard deviation (reliability indicator) |
| `coeff_variation` | `double` | YES | — | Coefficient of variation |
| `total_current_travel_time_sec` | `double` | YES | — | Sum of current travel times across all segments |
| `total_freeflow_travel_time_sec` | `double` | YES | — | Sum of freeflow travel times |
| `total_typical_travel_time_sec` | `double` | YES | — | Sum of typical travel times |
| `p95_travel_time_sec` | `double` | YES | — | 95th percentile travel time |
| `avg_delay_pct` | `double` | YES | — | Average delay % (vs typical) |
| `avg_delay_seconds` | `integer` | YES | — | Average delay in seconds |
| `avg_delay_intensity` | `double` | YES | — | Average delay per km |
| `segments_congested` | `integer` | YES | — | Count of congested segments |
| `segments_slow` | `integer` | YES | — | Count of slow segments |
| `segments_freeflow` | `integer` | YES | — | Count of freeflow segments |
| `segment_count` | `integer` | YES | — | Total segments in corridor |
| `sample_count` | `integer` | YES | — | Number of observations |
| `updated_at` | `timestamp` | YES | `now()` | — |
| `avg_delay_pct_ff` | `double` | YES | — | Average delay % (vs freeflow) |
| `avg_delay_seconds_ff` | `integer` | YES | — | Average delay in seconds (vs freeflow) |

**Primary Key**: `(corridor_id, bucket_start_time)`
**Indexes**: `bucket_start_time DESC`, `(corridor_id, bucket_start_time DESC)`, `(corridor_id, day_of_week, hour_of_day)`, partial index on congested corridors

---

### 3.10 `public.cities`

> **Purpose**: Master list of monitored cities. Parent entity for the entire road hierarchy.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `city_id` | `varchar(100)` | NO | — | **PK**. Unique city identifier |
| `city_name` | `varchar(255)` | NO | — | **UNIQUE**. City display name |
| `geometry` | `geometry` (PostGIS) | YES | — | City boundary polygon |
| `centroid` | `geometry` (PostGIS) | YES | — | City center point |
| `organization_id` | `varchar(100)` | YES | — | Owning organization |
| `is_active` | `boolean` | YES | `true` | Whether city is actively monitored |
| `created_at` | `timestamp` | YES | `CURRENT_TIMESTAMP` | — |
| `bbox` | `double[]` (array) | YES | — | Bounding box coordinates `[minLng, minLat, maxLng, maxLat]` |

**Primary Key**: `city_id`
**Unique**: `city_name`
**Indexes**: `city_id`, `city_name`, `organization_id`, `is_active`

---

## 4. Schema: `road_hierarchy` — Geographic Hierarchy Tables

### 4.1 `road_hierarchy.zone`

> **Purpose**: Top-level geographic zone within a city (e.g., "North Zone", "South Zone").

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `zone_id` | `varchar(35)` | NO | `generate_id('zon')` | **PK**. Auto-generated ULID-style ID with `zon_` prefix |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `zone_name` | `varchar(150)` | NO | — | Display name |
| `norm_name` | `text` | YES | — | Normalized name (lowercase, trimmed, single-spaced). Used for dedup. |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Unique**: `(city_id, norm_name)`

### 4.2 `road_hierarchy.corridor`

> **Purpose**: A traffic corridor — a major route/highway that may span multiple zones.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `corridor_id` | `varchar(35)` | NO | `generate_id('cor')` | **PK** |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `corridor_name` | `varchar(300)` | NO | — | Display name |
| `norm_name` | `text` | YES | — | Normalized for dedup |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Unique**: `(city_id, norm_name)`

### 4.3 `road_hierarchy.corridor_zone_map`

> **Purpose**: Links corridors to zones (many-to-many). One corridor can cross multiple zones.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `corridor_id` | `varchar(35)` | NO | — | **PK (part 1)** + **FK** → `corridor.corridor_id` |
| `zone_id` | `varchar(35)` | NO | — | **PK (part 2)** + **FK** → `zone.zone_id` |
| `is_primary` | `boolean` | NO | `true` | Whether this is the corridor's primary zone |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Unique partial index**: `(corridor_id) WHERE is_primary = true AND is_active = true` — enforces only one active primary zone per corridor

### 4.4 `road_hierarchy.road_master`

> **Purpose**: Canonical road names. Multiple road segments can belong to the same logical road.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_master_id` | `varchar(35)` | NO | `generate_id('rms')` | **PK** |
| `road_master_name` | `varchar(200)` | NO | — | Canonical road name |
| `norm_name` | `text` | YES | — | **UNIQUE**. Normalized name for dedup |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

### 4.5 `road_hierarchy.road_corridor_map`

> **Purpose**: Links roads to corridors (many-to-many).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_master_id` | `varchar(35)` | NO | — | **PK (part 1)** + **FK** → `road_master.road_master_id` |
| `corridor_id` | `varchar(35)` | NO | — | **PK (part 2)** + **FK** → `corridor.corridor_id` |
| `is_primary` | `boolean` | NO | `true` | Primary corridor for this road |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Unique partial index**: `(road_master_id) WHERE is_primary = true AND is_active = true`

### 4.6 `road_hierarchy.division`

> **Purpose**: Administrative division within a city (e.g., police division, traffic division).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `division_id` | `varchar(35)` | NO | `generate_id('div')` | **PK** |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `division_name` | `varchar(150)` | NO | — | — |
| `norm_name` | `text` | YES | — | Normalized |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Unique**: `(city_id, norm_name)`

### 4.7 `road_hierarchy.locality`

> **Purpose**: Neighborhood/locality within a city.

Same structure as `division` but with `locality_id` (prefix `loc_`) and `locality_name`.
**Unique**: `(city_id, norm_name)`

### 4.8 `road_hierarchy.sub_locality`

> **Purpose**: Sub-neighborhood within a locality.

Same structure but with `sub_locality_id` (prefix `slc_`) and `sub_locality_name`.
**Unique**: `(city_id, norm_name)`

### 4.9 `road_hierarchy.postal_code`

> **Purpose**: Postal/PIN code lookup.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `postal_code_id` | `varchar(35)` | NO | `generate_id('poc')` | **PK** |
| `postal_code` | `varchar(20)` | NO | — | **UNIQUE**. Actual postal code string |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

### 4.10 Segment Mapping Tables

#### `road_hierarchy.segment_hierarchy`

> **Purpose**: **Denormalized flat table** — one row per segment with all hierarchy names inline. This is the source-of-truth that gets parsed into the normalized mapping tables. Created from geocode results.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `segment_id` | `varchar(100)` | NO | — | **PK**. = `road_segment.road_id` |
| `road_segment` | `text` | NO | — | Original road segment name from data |
| `matched_road` | `text` | YES | — | Road name matched by fuzzy matching |
| `match_score` | `numeric(6,3)` | YES | — | Fuzzy match confidence (0-1) |
| `road_master_name` | `varchar(200)` | YES | — | Matched canonical road name |
| `corridor_name` | `varchar(300)` | NO | — | Corridor assignment |
| `division_name` | `varchar(150)` | NO | — | Division assignment |
| `locality` | `varchar(150)` | YES | — | Locality |
| `sub_locality` | `varchar(150)` | YES | — | Sub-locality |
| `postal_code` | `varchar(20)` | YES | — | PIN/postal code |
| `zone_name` | `varchar(150)` | YES | — | Zone |
| `city_name` | `varchar(150)` | YES | — | City |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Indexes**: `segment_id`, `city_name`, `zone_name`, `corridor_name`, `division_name`, `postal_code`

#### `road_hierarchy.segment_road_map`

> Maps segment → road_master (PK: `segment_id`, FK: `road_master_id`). Includes `source` (default `'segment_hierarchy'`) and `match_score`.

#### `road_hierarchy.segment_division_map`

> Maps segment → division (PK: `segment_id`, FK: `division_id`).

#### `road_hierarchy.segment_local_map`

> Maps segment → locality + sub_locality + postal_code (PK: `segment_id`, FKs: `locality_id`, `sub_locality_id`, `postal_code_id`).

### 4.11 `road_hierarchy.junction`

> **Purpose**: Intersection/junction points in the road network. Each junction has a PostGIS point location and connects to road segments via `segment_junction_map`. Used for junction-level traffic analysis and turn-based routing.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `junction_id` | `varchar(35)` | NO | `generate_id('jxn')` | **PK**. Auto-generated ULID-style ID with `jxn_` prefix |
| `organization_id` | `varchar(100)` | NO | — | Tenant/organization identifier |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `junction_name` | `varchar(255)` | NO | — | Human-readable intersection name |
| `norm_name` | `text` | YES | — | Generated column: `normalize_name(junction_name)`. Used for dedup |
| `location` | `geometry(Point,4326)` | YES | — | PostGIS point for the junction (spatial indexed) |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Primary Key**: `junction_id`
**Unique**: `(city_id, norm_name)` — no duplicate junction names within a city
**Foreign Key**: `city_id` → `public.cities.city_id`
**Indexes**: `city_id`, `organization_id`, `(organization_id, is_active)`, spatial GIST on `location`
**Referenced by**: `segment_junction_map.junction_id`
**Trigger**: `trg_junction_updated_at` — auto-updates `updated_at` on UPDATE

---

### 4.12 `road_hierarchy.segment_junction_map`

> **Purpose**: Links road segments to junctions with directional and approach information. A junction can have multiple segments (arms), and each arm has a compass direction and approach label.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `junction_id` | `varchar(35)` | NO | — | **PK (part 1)** + **FK** → `junction.junction_id` (CASCADE delete) |
| `segment_id` | `varchar(100)` | NO | — | **PK (part 2)** + **FK** → `road_segment.road_id` (RESTRICT delete) |
| `approach_label` | `varchar(255)` | NO | — | Human-readable approach name (e.g., "From NH-16 North") |
| `direction` | `varchar(2)` | YES | — | Compass direction: `N`, `S`, `E`, `W`, `NE`, `NW`, `SE`, `SW` |
| `is_active` | `boolean` | NO | `true` | — |
| `created_at` | `timestamptz` | NO | `now()` | — |

**Primary Key**: `(junction_id, segment_id)`
**Foreign Keys**: `junction_id` → `junction.junction_id` (ON DELETE CASCADE), `segment_id` → `road_segment.road_id` (ON DELETE RESTRICT)
**Check Constraint**: `direction` must be one of N, S, E, W, NE, NW, SE, SW
**Indexes**: `junction_id`, `segment_id`, `(junction_id, is_active)`

---

### 4.13 `road_hierarchy.road_grid_mapping`

> **Purpose**: Maps road segments to spatial grid cells with overlap information. Each road segment can overlap multiple grid cells, and this table tracks how much of the road falls in each cell. Used to power `area_hourly_metrics` aggregation — linking per-road metrics to spatial areas.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `road_id` | `varchar(100)` | NO | — | **PK (part 1)** + **FK** → `road_segment.road_id` (CASCADE delete) |
| `grid_type` | `varchar(20)` | NO | — | **PK (part 2)**. Values: `locality`, `pincode`, `h3`, `geohash` |
| `grid_cell_id` | `varchar(64)` | NO | — | **PK (part 3)**. Cell identifier matching `area_hourly_metrics.grid_cell_id` |
| `resolution` | `smallint` | YES | — | Grid resolution. NULL for locality/pincode; required for h3 (1–15) and geohash (1–12) |
| `city_id` | `varchar(100)` | YES | — | **FK** → `public.cities.city_id` |
| `road_length_in_cell_m` | `integer` | NO | — | Length of the road within this cell in meters (must be > 0) |
| `overlap_fraction` | `numeric(7,4)` | NO | — | Fraction of the road in this cell (> 0 and ≤ 1.05, allows slight overshoot) |
| `created_at` | `timestamptz` | NO | `now()` | — |
| `updated_at` | `timestamptz` | NO | `now()` | — |

**Primary Key**: `(road_id, grid_type, grid_cell_id)`
**Foreign Keys**: `road_id` → `road_segment.road_id` (CASCADE), `city_id` → `public.cities.city_id`
**Check Constraints**: `grid_type` in (locality, pincode, h3, geohash), `road_length_in_cell_m` > 0, `overlap_fraction` > 0 and ≤ 1.05, resolution NULL for locality/pincode and NOT NULL for h3/geohash, h3 resolution 1–15, geohash resolution 1–12
**Unique Constraints**: `(road_id, grid_cell_id, resolution) WHERE grid_type = 'geohash'`, `(road_id, grid_cell_id, resolution) WHERE grid_type = 'h3'`, `(road_id, grid_cell_id) WHERE grid_type = 'locality'`, `(road_id, grid_cell_id) WHERE grid_type = 'pincode'`
**Indexes**: `road_id`, `(grid_type, grid_cell_id)`, `(city_id, grid_type)`, `(grid_type, resolution) WHERE resolution IS NOT NULL`
**Trigger**: `trg_road_grid_mapping_updated_at` — auto-updates `updated_at` on UPDATE

---

### 4.14 `road_hierarchy.geocode_dump`

> **Purpose**: Raw Google Geocoding API responses per segment. Used as input to build the segment hierarchy.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `bigint` | NO | `nextval(seq)` | **PK** |
| `segment_id` | `varchar(100)` | NO | — | **UNIQUE** + **FK** → `road_segment.road_id` |
| `input_lat` | `numeric(15,10)` | NO | — | Latitude sent to geocode API |
| `input_lng` | `numeric(15,10)` | NO | — | Longitude sent to geocode API |
| `raw_response` | `jsonb` | NO | — | Full Google Geocoding API response (GIN indexed) |
| `api_status` | `varchar(50)` | YES | — | API response status |
| `city_name` | `varchar(100)` | YES | — | Extracted city |
| `state_name` | `varchar(100)` | YES | — | Extracted state |
| `country` | `varchar(100)` | YES | — | Extracted country |
| `zone_name` | `varchar(100)` | YES | — | Extracted zone |
| `corridor_name` | `varchar(200)` | YES | — | Extracted corridor |
| `corridor_source` | `varchar(50)` | YES | — | How corridor was determined |
| `corridor_type` | `varchar(50)` | YES | — | Corridor classification |
| `road_name` | `varchar(200)` | YES | — | Extracted road name |
| `road_short_name` | `varchar(100)` | YES | — | Short form |
| `formatted_address` | `text` | YES | — | Full formatted address |
| `google_place_id` | `varchar(200)` | YES | — | Google Place ID |
| `geocode_lat` | `numeric(15,10)` | YES | — | Returned latitude |
| `geocode_lng` | `numeric(15,10)` | YES | — | Returned longitude |
| `sublocality_2` | `varchar(100)` | YES | — | Secondary sublocality |
| `postal_code` | `varchar(20)` | YES | — | Postal code from geocode |
| `is_processed` | `boolean` | YES | `false` | Whether this has been processed into hierarchy |
| `processed_at` | `timestamptz` | YES | — | Processing timestamp |
| `created_at` | `timestamptz` | YES | `now()` | — |

**Indexes**: `id`, `segment_id` (unique), `(city_name, state_name)`, `api_status`, `is_processed` (partial: where false), `raw_response` (GIN)

### 4.12 `road_hierarchy.city_hierarchy_config`

> **Purpose**: Per-city configuration for hierarchy matching rules (e.g., which geocode fields to use for zone, corridor, road matching).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `bigint` | NO | `nextval(seq)` | **PK** |
| `city_id` | `varchar(100)` | NO | — | **FK** → `public.cities.city_id` |
| `city_name` | `varchar(100)` | NO | — | City name |
| `state_name` | `varchar(100)` | NO | — | State name |
| `zone_name` | `varchar(100)` | YES | — | Default zone name mapping |
| `corridor_name` | `varchar(200)` | YES | — | Corridor mapping config |
| `road_name` | `varchar(200)` | YES | — | Road mapping config |
| `match_sublocality` | `varchar(100)` | YES | — | Sublocality matching rule |
| `match_premise` | `varchar(100)` | YES | — | Premise matching rule |
| `match_route` | `varchar(200)` | YES | — | Route matching rule |
| `is_active` | `boolean` | YES | `true` | — |
| `created_at` | `timestamptz` | YES | `now()` | — |
| `updated_at` | `timestamptz` | YES | `now()` | — |

**Indexes**: `id`, `(city_id, is_active)`, `(city_name, state_name)`

---

## 5. Views

### 5.1 `public.traffic_segments_for_tiles`

> **Purpose**: Map tile layer view. Joins `road_segment` + `realtime_road_status` to produce tile-ready data with live traffic metrics for map display.

### 5.2 `road_hierarchy.v_segment_hierarchy`

> **Purpose**: Enriched segment hierarchy view. Joins `segment_hierarchy` with all dimension tables to resolve IDs (zone_id, corridor_id, road_master_id, division_id, locality_id, sub_locality_id, postal_code_id) plus the segment_name from road_segment.

**Join logic**: Uses `normalize_name()` function to match names across tables, scoped by city_id.

---

## 6. Helper Functions

### 6.1 `road_hierarchy.generate_id(prefix text) → text`

Generates a ULID-style ID: `{prefix}_{timestamp_base32}{random_base32}`. Used as default for all `road_hierarchy` primary keys.

- Format: `{prefix}_{10 chars timestamp}{16 chars random}` = ~29 chars total
- Alphabet: `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (Crockford Base32, no I/L/O/U)
- Result is lowercased

### 6.2 `road_hierarchy.normalize_name(input_text text) → text`

Normalizes text for deduplication: `trim(regexp_replace(lower(input), '\s+', ' ', 'g'))`. Immutable function.

---

## 7. Cross-Schema FK Bridge

The `road_hierarchy` schema references `public` schema tables via these cross-schema foreign keys:

| road_hierarchy table | Column | References |
|---------------------|--------|------------|
| `zone` | `city_id` | `public.cities.city_id` |
| `corridor` | `city_id` | `public.cities.city_id` |
| `division` | `city_id` | `public.cities.city_id` |
| `locality` | `city_id` | `public.cities.city_id` |
| `sub_locality` | `city_id` | `public.cities.city_id` |
| `junction` | `city_id` | `public.cities.city_id` |
| `road_grid_mapping` | `road_id` | `public.road_segment.road_id` |
| `road_grid_mapping` | `city_id` | `public.cities.city_id` |
| `segment_junction_map` | `junction_id` | `road_hierarchy.junction.junction_id` |
| `segment_junction_map` | `segment_id` | `public.road_segment.road_id` |
| `city_hierarchy_config` | `city_id` | `public.cities.city_id` |
| `geocode_dump` | `segment_id` | `public.road_segment.road_id` |
| `segment_hierarchy` | `segment_id` | `public.road_segment.road_id` |
| `segment_road_map` | `segment_id` | `public.road_segment.road_id` |
| `segment_division_map` | `segment_id` | `public.road_segment.road_id` |
| `segment_local_map` | `segment_id` | `public.road_segment.road_id` |

---

## 8. time_bucket_15m Encoding

The `time_bucket_15m` integer encodes a specific 15-minute window within a week. This is used in `realtime_road_status`.

### Formula

```
time_bucket_15m = (day_of_week_monday_zero * 96) + (hour * 4) + floor(minute / 15)
```

Where:
- `day_of_week_monday_zero` = `(EXTRACT(DOW FROM ts) + 6) % 7` — Monday=0, Tuesday=1, ..., Sunday=6
- `hour` = 0–23
- `minute / 15` = 0–3

### Range

- **Minimum**: 0 (Monday 00:00–00:14)
- **Maximum**: 671 (Sunday 23:45–23:59)
- **Total slots**: 672 (7 days × 96 quarter-hours)

### Reverse decode

```sql
-- From time_bucket_15m to day/time:
day_name = CASE (time_bucket_15m / 96)
  WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' ... WHEN 6 THEN 'Sunday' END
hour = (time_bucket_15m % 96) / 4
minute_start = ((time_bucket_15m % 96) % 4) * 15
```

### Get current bucket (IST timezone)

```sql
SELECT (((EXTRACT(DOW FROM now() AT TIME ZONE 'Asia/Kolkata')::int + 6) % 7) * 96)
     + (EXTRACT(HOUR FROM now() AT TIME ZONE 'Asia/Kolkata')::int * 4)
     + floor(EXTRACT(MINUTE FROM now() AT TIME ZONE 'Asia/Kolkata') / 15)::int
AS current_bucket;
```

---

## 9. Common Query Patterns

### Get current traffic status for all roads in a city

```sql
SELECT rs.road_id, rs.road_name, rrs.traffic_status, rrs.current_speed_kmph,
       rrs.delay_percent
FROM road_segment rs
JOIN realtime_road_status rrs ON rs.road_id = rrs.road_id
WHERE rs.tag = 'Kolkata';
```

### Get roads with hierarchy info (use the view)

```sql
SELECT * FROM road_hierarchy.v_segment_hierarchy
WHERE city_name = 'Kolkata' AND zone_name = 'South Zone';
```

### Active alerts with road details

```sql
SELECT a.alert_id, a.alert_type, a.alert_event_time, rs.road_name, rs.tag
FROM alert a
JOIN road_segment rs ON a.road_id = rs.road_id
WHERE a.current_status = 'ACTIVE'
ORDER BY a.alert_event_time DESC;
```

### Hourly speed trend for a road

```sql
SELECT bucket_start_time, avg_speed_kmph, avg_freeflow_speed_kmph, avg_delay_pct
FROM analytics_hourly_road_metrics
WHERE road_id = 'some_road_id'
  AND bucket_start_time >= now() - interval '7 days'
ORDER BY bucket_start_time;
```

### Network-level hourly speed trend

```sql
SELECT snapshot_date, hour_of_day, network_speed_kmph,
       network_freeflow_speed_kmph, congested_km, total_network_length_km,
       data_coverage_pct
FROM network_hourly_snapshot
WHERE organization_id = 'org_123'
  AND snapshot_date >= CURRENT_DATE - interval '7 days'
ORDER BY snapshot_date, hour_of_day;
```

### Area congestion heatmap (locality grid)

```sql
SELECT grid_cell_id, bucket_hour, avg_speed_kmph, congestion_pct,
       avg_delay_pct, road_count
FROM area_hourly_metrics
WHERE grid_type = 'locality'
  AND city_id = 'city_123'
  AND bucket_hour >= now() - interval '24 hours'
ORDER BY congestion_pct DESC;
```

### Corridor travel time trend

```sql
SELECT bucket_start_time, avg_speed_kmph, avg_freeflow_speed_kmph,
       total_current_travel_time_sec, total_freeflow_travel_time_sec,
       segments_congested, segment_count
FROM analytics_hourly_corridor_metrics
WHERE corridor_id = 'cor_abc'
  AND bucket_start_time >= now() - interval '7 days'
ORDER BY bucket_start_time;
```

### Junction arms with road details

```sql
SELECT j.junction_name, sjm.approach_label, sjm.direction,
       rs.road_name, rs.road_length_meters
FROM road_hierarchy.junction j
JOIN road_hierarchy.segment_junction_map sjm ON j.junction_id = sjm.junction_id
JOIN road_segment rs ON sjm.segment_id = rs.road_id
WHERE j.city_id = 'city_123' AND sjm.is_active = true;
```

### Roads in a specific grid cell with overlap info

```sql
SELECT rgm.road_id, rs.road_name, rgm.road_length_in_cell_m,
       rgm.overlap_fraction
FROM road_hierarchy.road_grid_mapping rgm
JOIN road_segment rs ON rgm.road_id = rs.road_id
WHERE rgm.grid_type = 'locality' AND rgm.grid_cell_id = 'Salt Lake';
```

### Alert lifecycle for a specific alert

```sql
SELECT event_action, severity, alert_event_time, reason, metrics_snapshot
FROM traffic_alert_lifecycle_log
WHERE alert_id = 123
ORDER BY created_at;
```

---

## 10. Backup / Legacy Tables (Ignore)

> **Note**: Backup tables (`alerts_backup`, `traffic_alert_lifecycle_log_backup`, `road_segment_*_backup`, etc.) and PostGIS/migration tables (`flyway_schema_history`, `spatial_ref_sys`) exist but should not be queried for application logic.
