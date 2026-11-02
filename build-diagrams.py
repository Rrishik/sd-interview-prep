import json
import os
import copy

BASE_DIR = r"d:\test\PersonalDocuments\sd-interview-prep"
DIAG_DIR = os.path.join(BASE_DIR, "diagrams")
LIB_DIR = os.path.join(DIAG_DIR, "libraries")

with open(os.path.join(LIB_DIR, "software-architecture.excalidrawlib"), "r", encoding="utf-8") as f:
    LIB_SW = json.load(f).get("library", [])

with open(os.path.join(LIB_DIR, "system-design-components.excalidrawlib"), "r", encoding="utf-8") as f:
    raw_sd = json.load(f)
    items_sd = raw_sd.get("libraryItems") or raw_sd.get("library") or []
    LIB_SD = [item["elements"] if isinstance(item, dict) else item for item in items_sd]

# LIB_SW indices:
# 1 = Kafka hub-and-spoke icon
# 2 = Redis 3D diamond stack icon
# 3 = Database cylinder icon
# 4 = Server rack icon
# 5 = Browser client icon
# 6 = Cache icon

# LIB_SD indices:
# 1 = Application server
# 2 = Multi Instance server
# 6 = Relational DB (cylinder)
# 7 = Object Storage
# 9 = Document DB
# 10 = Columnar DB (Cassandra/Scylla)
# 13 = Key/Value Cache
# 16 = Load Balancer
# 17 = Message Q
# 18 = Pipeline
# 20 = CDN
# 22 = Mobile
# 23 = Web Application


def make_scene(elements):
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": 20,
            "viewBackgroundColor": "#ffffff",
            "zenModeEnabled": True,
        },
        "files": {},
    }


def base_el(el_id, el_type, x, y, w, h, stroke="#1e293b", bg="transparent", sw=1.5, dash="solid", round_type=3):
    return {
        "id": el_id,
        "type": el_type,
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": bg,
        "fillStyle": "solid",
        "strokeWidth": sw,
        "strokeStyle": dash,
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": {"type": round_type} if round_type else None,
        "seed": abs(hash(el_id)) % 900000 + 1000,
        "version": 2,
        "versionNonce": abs(hash(el_id + "_v")) % 900000 + 1000,
        "isDeleted": False,
        "boundElements": [],
        "updated": 1711800000000,
        "link": None,
        "locked": False,
    }


def text_el(el_id, x, y, w, h, txt, size=14, family=2, color="#0f172a", align="left", valign="top", container=None):
    el = base_el(el_id, "text", x, y, w, h, stroke=color, bg="transparent", sw=1, round_type=None)
    el.update({
        "text": txt,
        "fontSize": size,
        "fontFamily": family,
        "textAlign": align,
        "verticalAlign": valign,
        "containerId": container,
        "originalText": txt,
        "lineHeight": 1.25,
        "autoResize": True,
    })
    return el


def stamp_lib(els, lib_items, idx, prefix, tx, ty, tw, th, stroke=None, bg=None, keep_text=False):
    """Stamps a System Design Library block scaled into (tx, ty, tw, th) in Minimal Architect style."""
    raw_els = copy.deepcopy(lib_items[idx])
    if not keep_text:
        raw_els = [e for e in raw_els if e.get("type") != "text"]
    if not raw_els:
        return

    min_x = min(e.get("x", 0) for e in raw_els)
    min_y = min(e.get("y", 0) for e in raw_els)
    max_x = max(e.get("x", 0) + max(abs(e.get("width", 0)), 1) for e in raw_els)
    max_y = max(e.get("y", 0) + max(abs(e.get("height", 0)), 1) for e in raw_els)
    src_w = max(max_x - min_x, 1.0)
    src_h = max(max_y - min_y, 1.0)

    scale = min(tw / src_w, th / src_h)
    ox = tx + (tw - src_w * scale) / 2.0
    oy = ty + (th - src_h * scale) / 2.0
    grp_id = f"grp_{prefix}"

    for i, e in enumerate(raw_els):
        etype = e.get("type", "rectangle")
        if etype == "draw":
            etype = "freedraw"
        nx = ox + (e.get("x", 0) - min_x) * scale
        ny = oy + (e.get("y", 0) - min_y) * scale
        nw = max(abs(e.get("width", 10)) * scale, 1.0)
        nh = max(abs(e.get("height", 10)) * scale, 1.0)

        sc = stroke if stroke else e.get("strokeColor", "#1e293b")
        bc = e.get("backgroundColor", "transparent")
        if bg and bc != "transparent":
            bc = bg

        clean = base_el(
            f"{prefix}_lib_{i}",
            etype,
            nx,
            ny,
            nw,
            nh,
            stroke=sc,
            bg=bc,
            sw=1.5,
            dash=e.get("strokeStyle", "solid"),
            round_type=3 if etype == "rectangle" else None,
        )
        clean["groupIds"] = [grp_id]
        clean["boundElements"] = []

        if etype in ("line", "arrow", "freedraw"):
            pts = e.get("points", [[0, 0], [nw, nh]])
            clean["points"] = [[float(p[0]) * scale, float(p[1]) * scale] for p in pts]
            clean["lastCommittedPoint"] = None
            clean["startBinding"] = None
            clean["endBinding"] = None
            clean["startArrowhead"] = e.get("startArrowhead")
            clean["endArrowhead"] = e.get("endArrowhead")
            if etype == "freedraw":
                clean["pressures"] = []
                clean["simulatePressure"] = True
        elif etype == "text":
            clean.update({
                "text": e.get("text", ""),
                "originalText": e.get("text", ""),
                "fontSize": max(int(e.get("fontSize", 14) * scale), 10),
                "fontFamily": 2,
                "textAlign": e.get("textAlign", "center"),
                "verticalAlign": e.get("verticalAlign", "middle"),
                "containerId": None,
                "lineHeight": 1.2,
                "autoResize": True,
            })

        els.append(clean)


def lib_node(
    els,
    node_id,
    x,
    y,
    w,
    h,
    title,
    subtitle,
    lib_source,
    lib_idx,
    stroke="#1e293b",
    bg="#f8fafc",
    icon_bg=None,
    code_font=False,
):
    """Creates a Minimal Architect card with a stamped System Design Library icon on the left/top and crisp Helvetica/Cascadia text."""
    r = base_el(node_id, "rectangle", x, y, w, h, stroke=stroke, bg=bg, sw=1.5)
    els.append(r)

    # Stamp the system design library icon on the left side of the card
    icon_size = min(h - 24, 48)
    ix = x + 14
    iy = y + (h - icon_size) / 2.0
    stamp_lib(els, lib_source, lib_idx, f"{node_id}_ico", ix, iy, icon_size, icon_size, stroke=stroke, bg=icon_bg or bg)

    # Text block to the right of the icon
    tx = ix + icon_size + 12
    tw = w - (icon_size + 34)
    full_txt = f"{title}\n{subtitle}" if subtitle else title
    lines = full_txt.count("\n") + 1
    th = min(h - 12, max(lines * 19, 36))
    ty = y + (h - th) / 2.0
    els.append(
        text_el(
            f"{node_id}_txt",
            tx,
            ty,
            tw,
            th,
            full_txt,
            size=13,
            family=3 if code_font else 2,
            color="#0f172a",
            align="left",
            valign="middle",
        )
    )


def card(els, box_id, x, y, w, h, label, stroke="#1e293b", bg="#f8fafc", size=13, family=2, sw=1.5, dash="solid"):
    r = base_el(box_id, "rectangle", x, y, w, h, stroke=stroke, bg=bg, sw=sw, dash=dash)
    tid = box_id + "_txt"
    r["boundElements"] = [{"type": "text", "id": tid}]
    t = text_el(tid, x + 8, y + 8, w - 16, h - 16, label, size=size, family=family, color="#0f172a", align="center", valign="middle", container=box_id)
    els.extend([r, t])


def container(els, cid, x, y, w, h, title, stroke="#94a3b8", dash="dashed"):
    r = base_el(cid, "rectangle", x, y, w, h, stroke=stroke, bg="transparent", sw=1.5, dash=dash)
    t = text_el(cid + "_lbl", x + 14, y + 8, w - 28, 24, title, size=13, family=2, color="#334155")
    els.extend([r, t])


def arrow(els, aid, x1, y1, x2, y2, label=None, stroke="#475569", dash="solid"):
    dx, dy = x2 - x1, y2 - y1
    a = base_el(aid, "arrow", x1, y1, max(abs(dx), 1), max(abs(dy), 1), stroke=stroke, bg="transparent", sw=1.5, dash=dash, round_type=2)
    a.update({
        "points": [[0.0, 0.0], [float(dx), float(dy)]],
        "lastCommittedPoint": None,
        "startBinding": None,
        "endBinding": None,
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "elbowed": False,
    })
    els.append(a)
    if label:
        mx = x1 + dx / 2.0 - 55
        my = y1 + dy / 2.0 - 20
        els.append(text_el(aid + "_lbl", mx, my, 110, 20, label, size=11, family=3, color="#334155", align="center"))


# ==============================================================================
# DIAGRAM 1: 01-kafka-and-redis.excalidraw
# ==============================================================================
els1 = []
els1.append(text_el("k_title", 40, 18, 980, 34, "Kafka Partition Parallelism & Redis Atomic Data Structures", size=22, family=2))
els1.append(text_el("k_sub", 40, 52, 980, 22, "System Design Library Components  •  Hash(key) % N Ordering  •  Single-Thread In-Memory Primitives", size=13, family=3, color="#475569"))

container(els1, "c_kafka", 40, 90, 980, 235, "1. APACHE KAFKA: PARTITIONED APPEND-ONLY LOG & CONSUMER GROUP RULE", stroke="#047857", dash="solid")

lib_node(els1, "k_prod", 60, 135, 230, 85, "Event Producer", "key = user_id\nHash(user_id) % 3", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")
lib_node(els1, "k_p0", 355, 125, 290, 52, "Partition 0 (Log)", "[off 0] [off 1] [off 2] ->", LIB_SD, 18, stroke="#047857", bg="#d1fae5", code_font=True)
lib_node(els1, "k_p1", 355, 187, 290, 52, "Partition 1 (Log)", "[off 0] [off 1] ->", LIB_SD, 18, stroke="#047857", bg="#d1fae5", code_font=True)
lib_node(els1, "k_p2", 355, 249, 290, 52, "Partition 2 (Log)", "[off 0] [off 1] [off 2] ->", LIB_SD, 18, stroke="#047857", bg="#d1fae5", code_font=True)

lib_node(els1, "k_w1", 715, 125, 280, 52, "Consumer Worker 1", "Reads P0 sequentially", LIB_SD, 1, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els1, "k_w2", 715, 187, 280, 52, "Consumer Worker 2", "Reads P1 sequentially", LIB_SD, 1, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els1, "k_w3", 715, 249, 280, 52, "Consumer Worker 3", "Reads P2 (Worker 4 = IDLE)", LIB_SD, 2, stroke="#1d4ed8", bg="#eff6ff")

arrow(els1, "ak1", 290, 165, 355, 150, "Alice -> P0")
arrow(els1, "ak2", 290, 180, 355, 213, "Bob -> P1")
arrow(els1, "ak3", 290, 195, 355, 275, "Carol -> P2")
arrow(els1, "ak4", 645, 150, 715, 150, "1:1 lock-free")
arrow(els1, "ak5", 645, 213, 715, 213, "1:1 lock-free")
arrow(els1, "ak6", 645, 275, 715, 275, "1:1 lock-free")

container(els1, "c_redis", 40, 350, 980, 210, "2. REDIS: FOUR ATOMIC IN-MEMORY DATA STRUCTURES (SINGLE-THREADED EVENT LOOP)", stroke="#b45309", dash="solid")

lib_node(els1, "r_str", 60, 395, 225, 140, "1. String (O(1))", "SET notif:99 1 NX EX 86400\n• Idempotency lock\n• Rate-limit counter", LIB_SW, 2, stroke="#dc2626", bg="#fef2f2")
lib_node(els1, "r_lst", 300, 395, 225, 140, "2. List (O(1))", "RPUSH digest:u42 msg\n• Batch event buffer\n• Feed post_id queue", LIB_SD, 17, stroke="#b45309", bg="#fffbeb")
lib_node(els1, "r_zst", 540, 395, 225, 140, "3. Sorted Set (ZSET)", "ZADD timers 10:15 u42\n• ZRANGEBYSCORE <= NOW\n• Delayed timers & ranks", LIB_SD, 13, stroke="#047857", bg="#ecfdf5")
lib_node(els1, "r_hsh", 780, 395, 225, 140, "4. Hash (O(1))", "HSET sess:u42 gw gw-7\n• WebSocket routing\n• User config cache", LIB_SW, 6, stroke="#6d28d9", bg="#f5f3ff")


# ==============================================================================
# DIAGRAM 2: 02-database-sharding-keys.excalidraw
# ==============================================================================
els2 = []
els2.append(text_el("d_title", 40, 18, 980, 34, "Database Keys, Sharding & Storage Engines (B-Tree vs LSM-Tree)", size=22, family=2))
els2.append(text_el("d_sub", 40, 52, 980, 22, "Partition Key = Which Physical Node (Hash)   |   Sort Key = Contiguous Order on Disk", size=13, family=3, color="#475569"))

container(els2, "c_pk", 40, 90, 980, 195, "1. COMPOSITE PRIMARY KEY ROUTING:  PRIMARY KEY ( (user_id),  created_at DESC )", stroke="#1d4ed8", dash="solid")
lib_node(els2, "d_q", 60, 135, 255, 125, "Application Query", "WHERE user_id = 'u_42'\nORDER BY created_at DESC\nLIMIT 20", LIB_SD, 1, stroke="#334155", bg="#f8fafc", code_font=True)
lib_node(els2, "d_hash", 375, 135, 265, 125, "1. Partition Router", "Murmur3('u_42') -> Token 74\nRoutes directly to Shard #3\n(No scatter-gather!)", LIB_SD, 16, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els2, "d_disk", 700, 135, 300, 125, "2. Shard #3 Storage", "Seeks to 'u_42' on disk\nReads 20 contiguous rows\nsorted by created_at (<3 ms)", LIB_SD, 10, stroke="#047857", bg="#ecfdf5")
arrow(els2, "ad1", 315, 197, 375, 197, "O(1) hop")
arrow(els2, "ad2", 640, 197, 700, 197, "1 disk seek")

container(els2, "c_eng", 40, 310, 980, 225, "2. STORAGE ENGINE COMPARISON: RELATIONAL B-TREE vs COLUMNAR / LOG LSM-TREE", stroke="#64748b", dash="dashed")
lib_node(els2, "d_btree", 60, 355, 450, 155, "B-Tree (PostgreSQL / MySQL InnoDB)", "• Updates 16 KB pages in place + WAL\n• Fast predictable reads (1 canonical tree)\n• Row/page locks cap writes at ~5k–10k/s per primary\n• Best for: Users, Billing, ACID inventory", LIB_SD, 6, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els2, "d_lsm", 550, 355, 450, 155, "LSM-Tree (Cassandra / ScyllaDB / DynamoDB)", "• Appends to sequential WAL + RAM MemTable (lock-free)\n• Flushes immutable SSTables; Bloom filter skips misses\n• Absorbs 50k–100k+ writes/sec per node\n• Best for: Chat messages, Notification logs, Events", LIB_SD, 10, stroke="#b45309", bg="#fffbeb")


# ==============================================================================
# DIAGRAM 3: 03-notification-system.excalidraw (Clean blog version, no mock0!)
# ==============================================================================
els3 = []
els3.append(text_el("n_title", 40, 18, 1020, 34, "Global Notification System & 15-Minute AI Smart Digest (30,000 Peak QPS)", size=22, family=2))
els3.append(text_el("n_sub", 40, 52, 1020, 22, "Priority-Isolated Kafka Topics  •  Redis NX Deduplication  •  ZSET 15m Timer  •  LLM Circuit Breaker", size=13, family=3, color="#475569"))

container(els3, "cn_ing", 40, 90, 270, 440, "1. INGESTION & STORAGE", stroke="#334155", dash="solid")
lib_node(els3, "n_gw", 58, 130, 234, 82, "API Gateway", "POST /v1/notify\nRate limit + Auth", LIB_SD, 16, stroke="#334155", bg="#f8fafc")
lib_node(els3, "n_svc", 58, 240, 234, 92, "Ingestion Service", "Validates payload\nReturns 202 (<50 ms)", LIB_SD, 2, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els3, "n_cache", 58, 360, 234, 72, "User Prefs Cache", "Redis + Postgres DB", LIB_SW, 2, stroke="#b45309", bg="#fffbeb")
lib_node(els3, "n_logdb", 58, 445, 234, 72, "Notification Log DB", "Cassandra (user_id, ts)", LIB_SD, 10, stroke="#1d4ed8", bg="#eff6ff")
arrow(els3, "an1", 175, 212, 175, 240)
arrow(els3, "an2", 175, 332, 175, 360)

container(els3, "cn_high", 340, 90, 720, 205, "2. REAL-TIME HIGH-PRIORITY PATH (OTP / FRAUD / SECURITY ALERTS)", stroke="#047857", dash="solid")
lib_node(els3, "n_kh", 360, 135, 205, 135, "Kafka: notif.high", "Keyed by user_id\nIsolated from promos", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")
lib_node(els3, "n_wh", 605, 135, 220, 135, "Delivery Workers", "1. Redis SET notif_id NX\n2. Send APNs/FCM/SMS\n3. 5xx -> Retry / DLQ", LIB_SD, 2, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els3, "n_out", 860, 135, 180, 135, "Push / SMS / Email", "APNs • FCM • SES\nExponential backoff", LIB_SD, 22, stroke="#334155", bg="#f8fafc")
arrow(els3, "an3", 292, 270, 360, 195, "high prio")
arrow(els3, "an4", 565, 202, 605, 202)
arrow(els3, "an5", 825, 202, 860, 202)

container(els3, "cn_low", 340, 320, 720, 210, "3. 15-MINUTE AI SMART DIGEST PATH (LOW-PRIORITY SOCIAL & PROMO ALERTS)", stroke="#6d28d9", dash="solid")
lib_node(els3, "n_kl", 360, 365, 195, 140, "Kafka: notif.low", "Keyed by user_id\nAbsorbs promo spikes", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")
lib_node(els3, "n_red", 590, 365, 225, 140, "Redis Digest Buffer", "RPUSH items:u42 msg\nZADD timers 10:15 u42\nPolls ZRANGEBYSCORE", LIB_SW, 2, stroke="#b45309", bg="#fffbeb")
lib_node(els3, "n_llm", 850, 365, 190, 140, "LLM Digest Worker", "1 batched prompt/15m\n2s Circuit Breaker ->\nTemplate fallback", LIB_SD, 1, stroke="#6d28d9", bg="#f5f3ff")
arrow(els3, "an6", 292, 300, 360, 425, "low prio")
arrow(els3, "an7", 555, 435, 590, 435)
arrow(els3, "an8", 815, 435, 850, 435, "due batch")


# ==============================================================================
# DIAGRAM 4: 03-core-case-studies.excalidraw
# ==============================================================================
els4 = []
els4.append(text_el("cs_title", 40, 18, 980, 34, "Four Core System Design Patterns: Rate Limiter, Feed Fan-Out, Chat & Ticketing", size=22, family=2))
els4.append(text_el("cs_sub", 40, 52, 980, 22, "Token Bucket Lua  •  Hybrid Push/Pull Fan-Out  •  WebSocket Session Registry  •  2-Phase Seat Hold", size=13, family=3, color="#475569"))

container(els4, "cs_b1", 40, 90, 475, 205, "A. DISTRIBUTED RATE LIMITER (TOKEN BUCKET)", stroke="#1d4ed8", dash="solid")
lib_node(els4, "cs_gw", 58, 135, 200, 135, "API Gateway", "Intercepts request\nChecks user quota", LIB_SD, 16, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els4, "cs_rl", 285, 135, 210, 135, "Redis Lua Bucket", "EVALSHA: refill +\ndecrement atomically\n(<1 ms, zero race)", LIB_SW, 2, stroke="#b45309", bg="#fffbeb")
arrow(els4, "acs1", 258, 202, 285, 202)

container(els4, "cs_b2", 545, 90, 475, 205, "B. HYBRID NEWS FEED FAN-OUT (CELEBRITY SPLIT)", stroke="#047857", dash="solid")
lib_node(els4, "cs_fn", 563, 135, 210, 135, "Normal (<10k)", "Fan-out on WRITE:\nKafka pushes post_id\nto follower Redis lists", LIB_SD, 17, stroke="#047857", bg="#ecfdf5")
lib_node(els4, "cs_fc", 790, 135, 210, 135, "Celebrity (>10k)", "Fan-out on READ:\nWrite once; merge at\nfollower read time", LIB_SD, 13, stroke="#6d28d9", bg="#f5f3ff")

container(els4, "cs_b3", 40, 320, 475, 205, "C. REAL-TIME CHAT (WEBSOCKET + REDIS REGISTRY)", stroke="#6d28d9", dash="solid")
lib_node(els4, "cs_ws", 58, 365, 200, 135, "Chat Gateway #74", "Holds open TCP\nWebSocket to Bob", LIB_SD, 2, stroke="#6d28d9", bg="#f5f3ff")
lib_node(els4, "cs_rg", 285, 365, 210, 135, "Session Registry", "HSET sess:Bob gw-74\n+ Cassandra msg log\n((chat_id, bucket), id)", LIB_SD, 10, stroke="#b45309", bg="#fffbeb")
arrow(els4, "acs2", 258, 432, 285, 432)

container(els4, "cs_b4", 545, 320, 475, 205, "D. FLASH-SALE TICKETING (2-PHASE SEAT HOLD)", stroke="#dc2626", dash="solid")
lib_node(els4, "cs_th", 563, 365, 210, 135, "1. Redis 5m Hold", "SET seat:9A Alice\nNX EX 300\nBlocks 49,999 others", LIB_SW, 2, stroke="#dc2626", bg="#fef2f2")
lib_node(els4, "cs_td", 790, 365, 210, 135, "2. ACID DB Commit", "Postgres UPDATE seat\nWHERE status=AVAIL\nAuto-frees on timeout", LIB_SD, 6, stroke="#1d4ed8", bg="#eff6ff")
arrow(els4, "acs3", 773, 432, 790, 432)


# ==============================================================================
# DIAGRAM 5: 04-rag-and-agents.excalidraw
# ==============================================================================
els5 = []
els5.append(text_el("ai_title", 40, 18, 980, 34, "Enterprise Hybrid RAG, Pre-Retrieval ACL Security & Agent Guardrails", size=22, family=2))
els5.append(text_el("ai_sub", 40, 52, 980, 22, "ACL Metadata Pre-Filter  •  BM25 + HNSW Vector RRF  •  Cross-Encoder Reranker  •  Async Kafka Eval", size=13, family=3, color="#475569"))

container(els5, "ai_c1", 40, 90, 980, 205, "1. TWO-STAGE HYBRID RAG PIPELINE (WITH MANDATORY PRE-RETRIEVAL ACL FILTERING)", stroke="#1d4ed8", dash="solid")
lib_node(els5, "ai_q", 58, 135, 205, 135, "1. Query + User ACL", "groups = ['eng']\nCheck Semantic Cache\nscoped by ACL hash", LIB_SD, 14, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els5, "ai_hy", 300, 135, 235, 135, "2. Hybrid Search (Top 50)", "BM25 + HNSW Vector\nWHERE acl IN ['eng']\nMerged via RRF (~30 ms)", LIB_SD, 9, stroke="#047857", bg="#ecfdf5")
lib_node(els5, "ai_rr", 575, 135, 200, 135, "3. Cross-Encoder", "Reranks 50 -> Top 5\ngold chunks (~60 ms)\nCuts prompt tokens 10x", LIB_SD, 18, stroke="#b45309", bg="#fffbeb")
lib_node(els5, "ai_st", 810, 135, 190, 135, "4. Streamed LLM", "SSE token stream\nwith [doc_id] citations\nTTFT < 800 ms", LIB_SD, 23, stroke="#6d28d9", bg="#f5f3ff")
arrow(els5, "aai1", 263, 202, 300, 202)
arrow(els5, "aai2", 535, 202, 575, 202, "Top 50")
arrow(els5, "aai3", 775, 202, 810, 202, "Top 5")

container(els5, "ai_c2", 40, 320, 980, 205, "2. AGENT LOOP GUARDRAILS & ASYNCHRONOUS KAFKA EVALUATION PIPELINE", stroke="#6d28d9", dash="dashed")
lib_node(els5, "ai_ag", 58, 365, 290, 135, "Bounded ReAct Agent Loop", "• Max 5 steps & token budget cap\n• Read tools auto-run (server-bound ID)\n• Write tools require policy/human gate", LIB_SD, 2, stroke="#6d28d9", bg="#f5f3ff")
lib_node(els5, "ai_gw", 385, 365, 290, 135, "LLM Gateway & PII Shield", "• Scrubs SSN / secrets before prompt\n• Dual Token Bucket (RPM + TPM)\n• Circuit breaker -> fallback model", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els5, "ai_ev", 712, 365, 290, 135, "Async Eval (5% Kafka Sample)", "• Streams traces to Kafka -> Judge LLM\n• Scores Faithfulness & Context Recall\n• 0 ms added latency to user path!", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")

diagrams = {
    "01-kafka-and-redis.excalidraw": els1,
    "02-database-sharding-keys.excalidraw": els2,
    "03-notification-system.excalidraw": els3,
    "03-core-case-studies.excalidraw": els4,
    "04-rag-and-agents.excalidraw": els5,
    # Keep mock0-notification-system.excalidraw synced so existing links never break
    "mock0-notification-system.excalidraw": els3,
}

for fname, elements in diagrams.items():
    out_path = os.path.join(DIAG_DIR, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(make_scene(elements), f, indent=2)
    print(f"Wrote {fname} ({len(elements)} elements, including System Design Library blocks)")
