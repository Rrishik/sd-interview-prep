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

# ==============================================================================
# DIAGRAM 6: 05-agent-loops-memory.excalidraw
# ==============================================================================
els6 = []
els6.append(text_el("am_title", 40, 18, 980, 34, "Agent Loop Architectures (ReAct vs Adaptive DAG) & 3-Tier Memory Hierarchy", size=22, family=2))
els6.append(text_el("am_sub", 40, 52, 980, 22, "ReAct Loop  •  Plan-and-Execute DAG  •  Working / Episodic / Semantic Memory  •  KV Prefix Cache", size=13, family=3, color="#475569"))

container(els6, "am_c1", 40, 90, 980, 205, "1. AGENT ORCHESTRATION LOOPS: REACT VS. ADAPTIVE PLAN-AND-EXECUTE DAG", stroke="#1d4ed8", dash="solid")
lib_node(els6, "am_ra", 58, 135, 285, 135, "A. ReAct Loop (Dynamic)", "Thought -> Tool -> Observation\n• N sequential LLM turns\n• Best for exploratory tasks\n• Risk: unbounded latency/cost", LIB_SD, 2, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els6, "am_pe", 385, 135, 295, 135, "B. Plan-and-Execute (DAG)", "1. Planner builds dependency DAG\n2. Parallel tool wave execution\n3. Re-Planner only on step failure", LIB_SD, 18, stroke="#047857", bg="#ecfdf5")
lib_node(els6, "am_2p", 720, 135, 280, 135, "C. Two-Pass Guarded Flow", "Pass 1: Read-only diagnostics\nPass 2: Grounded action proposal\n• Predictable 2-hop latency\n• >90% precision (zero rogue write)", LIB_SD, 16, stroke="#6d28d9", bg="#f5f3ff")
arrow(els6, "aam1", 343, 202, 385, 202, "Add DAG")
arrow(els6, "aam2", 680, 202, 720, 202, "Privilege split")

container(els6, "am_c2", 40, 320, 980, 205, "2. THREE-TIER AGENT MEMORY ARCHITECTURE & KV PROMPT CACHING", stroke="#b45309", dash="solid")
lib_node(els6, "am_wm", 58, 365, 220, 135, "1. Working Memory", "Active context window\n• Plan scratchpad + state\n• Redis session TTL\n• Sliding summary buffer", LIB_SW, 2, stroke="#dc2626", bg="#fef2f2")
lib_node(els6, "am_em", 300, 365, 225, 135, "2. Episodic Memory", "Past session trajectories\n• What worked/failed before\n• pgvector + time-decay\n• Few-shot experience replay", LIB_SD, 9, stroke="#b45309", bg="#fffbeb")
lib_node(els6, "am_sm", 545, 365, 220, 135, "3. Semantic Memory", "Facts & domain knowledge\n• Hybrid BM25 + HNSW\n• Versioned fact upsert\n• Conflict resolution", LIB_SD, 6, stroke="#047857", bg="#ecfdf5")
lib_node(els6, "am_kv", 785, 365, 215, 135, "4. KV Prefix Cache", "[Static System + Tools]\nat immutable prefix\n• 80% lower TTFT & cost\n• Append-only history tail", LIB_SW, 6, stroke="#1d4ed8", bg="#eff6ff")


# ==============================================================================
# DIAGRAM 7: 06-mcp-evals-reactive.excalidraw
# ==============================================================================
els7 = []
els7.append(text_el("mc_title", 40, 18, 980, 34, "MCP Tool Architecture, RAG Evaluation Math & Reactive Agent Streaming", size=22, family=2))
els7.append(text_el("mc_sub", 40, 52, 980, 22, "Model Context Protocol (JSON-RPC)  •  Recall@K / MRR / nDCG@K  •  OpenTelemetry  •  Spring WebFlux SSE", size=13, family=3, color="#475569"))

container(els7, "mc_c1", 40, 90, 980, 205, "1. MODEL CONTEXT PROTOCOL (MCP), SANDboxed EXECUTION & PROMPT INJECTION DEFENSE", stroke="#047857", dash="solid")
lib_node(els7, "mc_cl", 58, 135, 220, 135, "Agent Host & MCP Client", "Spring AI / Orchestrator\n• JSON-RPC 2.0 transport\n• Discovers Tools/Resources\n• Injects caller auth token", LIB_SD, 1, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els7, "mc_gd", 305, 135, 225, 135, "Policy & Schema Gate", "• JSON Schema validation\n• Dual-LLM privilege split\n• Idempotency key check\n• HITL gate on write tools", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els7, "mc_sv", 555, 135, 215, 135, "MCP Server Registry", "Exposes 3 primitives:\n1. Tools (model-called)\n2. Resources (data URIs)\n3. Prompts (templates)", LIB_SD, 2, stroke="#047857", bg="#ecfdf5")
lib_node(els7, "mc_sb", 795, 135, 205, 135, "Sandboxed Runtime", "Isolated container / WASM\n• Egress allowlist\n• CPU/RAM/time quotas\n• Structured error JSON", LIB_SW, 4, stroke="#6d28d9", bg="#f5f3ff")
arrow(els7, "amc1", 278, 202, 305, 202)
arrow(els7, "amc2", 530, 202, 555, 202)
arrow(els7, "amc3", 770, 202, 795, 202)

container(els7, "mc_c2", 40, 320, 980, 205, "2. OBSERVABILITY (OPENTELEMETRY), RETRIEVAL METRICS & REACTIVE SSE STREAMING", stroke="#6d28d9", dash="solid")
lib_node(els7, "mc_rk", 58, 365, 290, 135, "Retrieval Metrics Suite", "• Recall@K = FoundRel / TotalRel\n• MRR = 1 / first_relevant_rank\n• nDCG@K = graded relevance discount\n• Isolates Retriever vs Generator", LIB_SD, 9, stroke="#b45309", bg="#fffbeb")
lib_node(els7, "mc_ot", 385, 365, 290, 135, "OpenTelemetry & Replay", "• Trace -> Run -> Step/Tool Spans\n• Token & cost accounting per tenant\n• Deterministic cassette tool replay\n• Canary rollout regression gates", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")
lib_node(els7, "mc_rx", 712, 365, 290, 135, "Reactive Backend (WebFlux)", "• Flux<ServerSentEvent> non-blocking\n• Event-loop handles 50k open streams\n• LongAdder striped atomic counters\n• Keyset pagination: (ts, id) < cursor", LIB_SD, 23, stroke="#1d4ed8", bg="#eff6ff")

# ==============================================================================
# DIAGRAM 8: 07-durable-agent-runtime.excalidraw
# ==============================================================================
els8 = []
els8.append(text_el("dr_title", 40, 18, 980, 34, "Durable Agent State Machine, Resumable Run API & 1M Runs/Day Scale", size=22, family=2))
els8.append(text_el("dr_sub", 40, 52, 980, 22, "Async Run API  •  Checkpointed Step Journal  •  Zero-Thread HITL Pause  •  Model Router & Token Quotas", size=13, family=3, color="#475569"))

container(els8, "dr_c1", 40, 90, 980, 205, "1. ASYNC RUN API & CHECKPOINTED DURABLE EXECUTION (SURVIVES WORKER CRASHES)", stroke="#1d4ed8", dash="solid")
lib_node(els8, "dr_api", 56, 135, 222, 135, "Async Run API", "POST /runs -> 202\nGET /events (SSE)\nPOST /approvals", LIB_SD, 16, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els8, "dr_q", 300, 135, 212, 135, "Kafka: agent.runs", "Keyed by run_id\nPriority tenant lanes\nBackpressure buffer", LIB_SW, 1, stroke="#047857", bg="#ecfdf5")
lib_node(els8, "dr_wk", 534, 135, 226, 135, "Stateless Workers", "1. 15s Redis lease\n2. Replay journal\n3. 0 threads on HITL", LIB_SD, 2, stroke="#6d28d9", bg="#f5f3ff")
lib_node(els8, "dr_db", 782, 135, 220, 135, "Journal & Stream", "Postgres step log\nRedis Last-Event-ID\nIdempotent recovery", LIB_SD, 6, stroke="#b45309", bg="#fffbeb")
arrow(els8, "adr1", 278, 202, 300, 202)
arrow(els8, "adr2", 512, 202, 534, 202)
arrow(els8, "adr3", 760, 202, 782, 202)

container(els8, "dr_c2", 40, 320, 980, 205, "2. SCALING TO 1M TASKS/DAY: TIERED MODEL ROUTING, FALLBACKS & TENANT TOKEN BUDGETS", stroke="#047857", dash="solid")
lib_node(els8, "dr_rt", 56, 365, 294, 135, "Tiered Model Router", "• 70% tasks -> small fast model\n• 30% hard -> frontier model\n• Sticky run_id KV affinity", LIB_SD, 18, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els8, "dr_cb", 383, 365, 294, 135, "Circuit Breaker", "• Tracks 429/5xx & TTFT SLO\n• Half-open health probes\n• Multi-region / provider failover", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els8, "dr_qt", 710, 365, 292, 135, "Tenant Token Ledger", "• Pre-flight Lua TPM reserve\n• Post-turn delta refund\n• Fair-queue isolation", LIB_SW, 2, stroke="#047857", bg="#ecfdf5")


# ==============================================================================
# DIAGRAM 9: 08-agent-case-studies.excalidraw
# ==============================================================================
els9 = []
els9.append(text_el("cs2_title", 40, 18, 980, 34, "End-to-End Agent System Designs: Coding Agent & Multi-Server Enterprise MCP", size=22, family=2))
els9.append(text_el("cs2_sub", 40, 52, 980, 22, "Ephemeral MicroVM Sandbox  •  Evaluator-Optimizer Loop  •  OAuth On-Behalf-Of (OBO)  •  Grounded Citations", size=13, family=3, color="#475569"))

container(els9, "cs2_c1", 40, 90, 980, 205, "A. AUTONOMOUS CODING & BUG-INVESTIGATION AGENT (SAFE REPOSITORY MUTATION)", stroke="#1d4ed8", dash="solid")
lib_node(els9, "cs2_in", 56, 135, 218, 135, "1. Bug Intake", "Stack trace + SHA\nBlame, recent PRs\n& call-graph index", LIB_SD, 9, stroke="#334155", bg="#f8fafc")
lib_node(els9, "cs2_vm", 296, 135, 224, 135, "2. MicroVM Box", "Git worktree clone\n• 0 prod secrets\n• Deny-all egress\n• rg + LSP tools", LIB_SW, 4, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els9, "cs2_eo", 542, 135, 226, 135, "3. Eval-Optimizer", "Edit -> Build -> Test\n• Max 4 repair loops\n• Structured diff\n  observations", LIB_SD, 18, stroke="#047857", bg="#ecfdf5")
lib_node(els9, "cs2_pr", 790, 135, 212, 135, "4. Draft PR Gate", "Isolated bot branch\n• Never merges main\n• Attaches test log", LIB_SD, 23, stroke="#6d28d9", bg="#f5f3ff")
arrow(els9, "acs2_1", 274, 202, 296, 202)
arrow(els9, "acs2_2", 520, 202, 542, 202)
arrow(els9, "acs2_3", 768, 202, 790, 202)

container(els9, "cs2_c2", 40, 320, 980, 205, "B. ENTERPRISE MULTI-MCP ASSISTANT & PARALLEL DEEP-RESEARCH SYNTHESIS", stroke="#b45309", dash="solid")
lib_node(els9, "cs2_mh", 56, 365, 220, 135, "1. MCP Host", "1:1 MCP Clients:\n• Git MCP Server\n• Jira MCP Server\n• SQL Analytics MCP", LIB_SD, 1, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els9, "cs2_ob", 298, 365, 224, 135, "2. OAuth OBO Gate", "Per-server JWT swap\n• Enforces user RLS\n• Blocks confused\n  deputy leaks", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els9, "cs2_prw", 544, 365, 224, 135, "3. Sub-Agent DAG", "Parallel read wave:\n• ACL-filtered RAG\n• Live MCP queries\n• Evidence cards", LIB_SD, 2, stroke="#047857", bg="#ecfdf5")
lib_node(els9, "cs2_cit", 790, 365, 212, 135, "4. Citation Check", "Verifies [doc:span]\nConsent diff card\nbefore any write", LIB_SW, 6, stroke="#b45309", bg="#fffbeb")
arrow(els9, "acs2_4", 276, 432, 298, 432)
arrow(els9, "acs2_5", 522, 432, 544, 432)
arrow(els9, "acs2_6", 768, 432, 790, 432)


# ==============================================================================
# DIAGRAM 10: 09-prompt-decoding-lora.excalidraw
# ==============================================================================
els10 = []
els10.append(text_el("pd_title", 40, 18, 980, 34, "Prompt Anatomy, Constrained Decoding (FSM/CFG), Parallel Tools & LoRA/QLoRA", size=22, family=2))
els10.append(text_el("pd_sub", 40, 52, 980, 22, "Token Logit Masking (Outlines / XGrammar)  •  Streamed Tool-ID Accumulators  •  Low-Rank Adapters (y = Wx + α/r BAx)", size=13, family=3, color="#475569"))

container(els10, "pd_c1", 40, 90, 980, 205, "1. PROMPT CONDITIONING, CONSTRAINED DECODING (FSM/CFG) & PARALLEL STREAMING TOOLS", stroke="#1d4ed8", dash="solid")
lib_node(els10, "pd_pr", 56, 135, 220, 135, "1. Prompt Layout", "System -> Tools -> Docs\nXML tags + start/end\ntemp XOR top_p", LIB_SD, 9, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els10, "pd_fs", 298, 135, 224, 135, "2. FSM Logit Mask", "JSON Schema -> CFG/FSM\nInvalid tokens = -inf\n100% valid or Refusal", LIB_SD, 18, stroke="#047857", bg="#ecfdf5")
lib_node(els10, "pd_ac", 544, 135, 224, 135, "3. Chunk Buffer", "Buffer per tool_call_id\nNever parse JSON early!\nCorrelate out-of-order", LIB_SW, 2, stroke="#b45309", bg="#fffbeb")
lib_node(els10, "pd_pf", 790, 135, 212, 135, "4. Parallel Fan-Out", "Concurrent executors\nWall time = max(t_i)\n60-70% latency cut", LIB_SD, 2, stroke="#6d28d9", bg="#f5f3ff")
arrow(els10, "apd1", 276, 202, 298, 202)
arrow(els10, "apd2", 522, 202, 544, 202)
arrow(els10, "apd3", 768, 202, 790, 202)

container(els10, "pd_c2", 40, 320, 980, 205, "2. PARAMETER-EFFICIENT FINE-TUNING: LORA LOW-RANK ADAPTERS & 4-BIT QLORA SERVING", stroke="#047857", dash="solid")
lib_node(els10, "pd_ql", 56, 365, 294, 135, "Frozen Base Weights (NF4)", "• 8B full FT = ~56 GB VRAM\n• 4-bit NF4 QLoRA = ~6 GB VRAM\n• Prevents catastrophic forgetting", LIB_SD, 6, stroke="#334155", bg="#f8fafc")
lib_node(els10, "pd_lr", 383, 365, 294, 135, "LoRA Adapter (Wx + α/r BAx)", "• r=16 on 4096x4096 = 0.78% params\n• Init A ~ N(0,σ²), B = 0 (clean start)\n• Ideal for style, format & planners", LIB_SD, 18, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els10, "pd_mg", 710, 365, 292, 135, "Merge vs S-LoRA Serving", "• Single adapter: W' = W + α/r BA\n  (0 ms extra inference latency!)\n• Multi-tenant: vLLM S-LoRA pool", LIB_SW, 4, stroke="#047857", bg="#ecfdf5")
arrow(els10, "apd4", 350, 432, 383, 432)
arrow(els10, "apd5", 677, 432, 710, 432)


# ==============================================================================
# DIAGRAM 11: 10-agent-harness-and-skills.excalidraw
# ==============================================================================
els11 = []
els11.append(text_el("ah_title", 40, 18, 980, 34, "Agent Harness ('Workbench') Architecture & Portable SKILL.md Disclosure", size=22, family=2))
els11.append(text_el("ah_sub", 40, 52, 980, 22, "7 Workbench Surfaces  •  Repo as System of Record  •  3-Tier Skill Disclosure  •  Worktree Wave Isolation", size=13, family=3, color="#475569"))

container(els11, "ah_c1", 40, 90, 980, 205, "1. THE 7-SURFACE AGENT HARNESS ('WORKBENCH') LOOP — REPOSITORY AS SYSTEM OF RECORD", stroke="#1d4ed8", dash="solid")
lib_node(els11, "ah_sc", 56, 135, 218, 135, "1. Scope & State", "Short AGENTS.md map\nTyped agent_state.json\nAllow/deny file globs", LIB_SD, 9, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els11, "ah_wk", 296, 135, 224, 135, "2. Worktree Run", "Isolated git worktree\nIdempotent init probe\nBounded log excerpts", LIB_SW, 4, stroke="#047857", bg="#ecfdf5")
lib_node(els11, "ah_vg", 542, 135, 226, 135, "3. Gate & Review", "Deterministic diff/test\nRead-only Reviewer\nBuilder != Marker!", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els11, "ah_ho", 790, 135, 212, 135, "4. Handoff Packet", "7-field state resume\nFeedback ratchet\n0 chat-history rot", LIB_SD, 6, stroke="#6d28d9", bg="#f5f3ff")
arrow(els11, "aah1", 274, 202, 296, 202)
arrow(els11, "aah2", 520, 202, 542, 202)
arrow(els11, "aah3", 768, 202, 790, 202)

container(els11, "ah_c2", 40, 320, 980, 205, "2. PORTABLE AGENT SKILLS (SKILL.MD) — 3-TIER PROGRESSIVE DISCLOSURE COMPILER", stroke="#b45309", dash="solid")
lib_node(els11, "ah_t1", 56, 365, 294, 135, "Tier 1: Compact Catalog", "• Scope precedence + collision rule\n• Name + positive/near-miss triggers\n• ~80 tokens/skill + abstain option", LIB_SD, 13, stroke="#b45309", bg="#fffbeb")
lib_node(els11, "ah_t2", 383, 365, 294, 135, "Tier 2: Active SKILL.md", "• Loaded only after trigger match\n• Procedural steps & output schema\n• Context != tool permission grant!", LIB_SD, 9, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els11, "ah_t3", 710, 365, 292, 135, "Tier 3: Bounded Resources", "• On-demand scripts & branch refs\n• realpath() blocks symlink escape\n• Verified via 6-layer skill evals", LIB_SW, 6, stroke="#047857", bg="#ecfdf5")
arrow(els11, "aah4", 350, 432, 383, 432, "On select")
arrow(els11, "aah5", 677, 432, 710, 432, "On demand")


# ==============================================================================
# DIAGRAM 12: 11-multimodal-cua-and-voice.excalidraw
# ==============================================================================
els12 = []
els12.append(text_el("mm_title", 40, 18, 980, 34, "Multimodal Agents: Computer-Use (GUI/DOM) & Sub-600ms Voice Pipelines", size=22, family=2))
els12.append(text_el("mm_sub", 40, 52, 980, 22, "Pixel/DOM Grounding  •  Untrusted Screen Rule  •  WebRTC Frame Pipeline  •  Upstream Barge-In Cancel", size=13, family=3, color="#475569"))

container(els12, "mm_c1", 40, 90, 980, 205, "1. COMPUTER-USE AGENT (CUA) LOOP — PIXEL GROUNDING & PER-STEP SAFETY GATE", stroke="#1d4ed8", dash="solid")
lib_node(els12, "mm_vm", 56, 135, 218, 135, "1. Virtual Display", "Isolated Xvfb / browser\nScreenshots + DOM\nDomain allowlists", LIB_SW, 5, stroke="#334155", bg="#f8fafc")
lib_node(els12, "mm_vg", 296, 135, 224, 135, "2. Pixel Grounding", "Predicts (x,y) action\nScreen = UNTRUSTED\nUser = sole authority", LIB_SD, 23, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els12, "mm_sf", 542, 135, 226, 135, "3. Per-Step Safety", "Pre-click classifier\nHITL on login/pay/del\nBlocks GUI injection", LIB_SD, 16, stroke="#dc2626", bg="#fef2f2")
lib_node(els12, "mm_ex", 790, 135, 212, 135, "4. Act & Observe", "Mouse / key dispatch\nPost-click visual diff\nOTel frame pointers", LIB_SD, 7, stroke="#047857", bg="#ecfdf5")
arrow(els12, "amm1", 274, 202, 296, 202)
arrow(els12, "amm2", 520, 202, 542, 202)
arrow(els12, "amm3", 768, 202, 790, 202)

container(els12, "mm_c2", 40, 320, 980, 205, "2. SUB-600MS REAL-TIME VOICE PIPELINE (BIDIRECTIONAL WEBRTC / PIPECAT FRAMES)", stroke="#6d28d9", dash="solid")
lib_node(els12, "mm_vd", 56, 365, 220, 135, "1. WebRTC + VAD", "UDP media (~45 ms)\nSilero VAD (~35 ms)\nSemantic turn-end", LIB_SD, 22, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els12, "mm_st", 298, 365, 222, 135, "2. Streaming STT", "Partial ASR (~150 ms)\nConfidence threshold\nStreams to LLM", LIB_SD, 18, stroke="#047857", bg="#ecfdf5")
lib_node(els12, "mm_lt", 542, 365, 224, 135, "3. LLM + TTS Pipe", "LLM TTFT (~200 ms)\nClause TTS (~150 ms)\nTotal E2E ~580 ms!", LIB_SD, 2, stroke="#6d28d9", bg="#f5f3ff")
lib_node(els12, "mm_bi", 788, 365, 214, 135, "4. Barge-In Ctrl", "User speaks mid-turn:\nUPSTREAM CancelFrame\nflushes TTS <50 ms", LIB_SW, 1, stroke="#b45309", bg="#fffbeb")
arrow(els12, "amm4", 276, 432, 298, 432)
arrow(els12, "amm5", 520, 432, 542, 432)
arrow(els12, "amm6", 766, 432, 788, 432, "Interrupt")


# ==============================================================================
# DIAGRAM 13: 12-llm-inference-serving.excalidraw
# ==============================================================================
els13 = []
els13.append(text_el("is_title", 40, 18, 980, 34, "LLM Inference & GPU Serving: Disaggregated Prefill/Decode, EAGLE-3 & Economics", size=22, family=2))
els13.append(text_el("is_sub", 40, 52, 980, 22, "Compute-Bound Prefill vs HBM-Bound Decode  •  Chunked Prefill  •  RDMA KV Bus  •  Goodput SLOs", size=13, family=3, color="#475569"))

container(els13, "is_c1", 40, 90, 980, 205, "1. DISAGGREGATED PREFILL & DECODE ARCHITECTURE (INDEPENDENT TTFT & TPOT SCALING)", stroke="#1d4ed8", dash="solid")
lib_node(els13, "is_rt", 56, 135, 218, 135, "1. KV-Aware Router", "Radix prefix affinity\nAdmission queue cap\nGoodput SLO guard", LIB_SD, 16, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els13, "is_pf", 296, 135, 224, 135, "2. Prefill Pool", "Compute-bound GEMMs\nChunked prefill 2k\nOptimizes TTFT SLO", LIB_SD, 2, stroke="#047857", bg="#ecfdf5")
lib_node(els13, "is_kv", 542, 135, 224, 135, "3. RDMA KV Bus", "NIXL / InfiniBand\nStreams FP8 KV blocks\nDecouples TTFT & ITL", LIB_SW, 2, stroke="#b45309", bg="#fffbeb")
lib_node(els13, "is_dc", 788, 135, 214, 135, "4. Decode Pool", "HBM-bandwidth bound\nPagedAttention batch\nKeeps TPOT ~7 ms", LIB_SW, 4, stroke="#6d28d9", bg="#f5f3ff")
arrow(els13, "ais1", 274, 202, 296, 202)
arrow(els13, "ais2", 520, 202, 542, 202)
arrow(els13, "ais3", 766, 202, 788, 202)

container(els13, "is_c2", 40, 320, 980, 205, "2. SPECULATIVE DECODING (EAGLE-3), QUANTIZATION & API VS SELF-HOSTED BREAK-EVEN", stroke="#047857", dash="solid")
lib_node(els13, "is_sp", 56, 365, 294, 135, "EAGLE-3 Speculative Head", "• Draft K=5 -> 1 target verify\n• Speedup ≈ (1 + K*α)/(1 + ε)\n• Net loss if α<0.55 or B>=64!", LIB_SD, 18, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els13, "is_qt", 383, 365, 294, 135, "Weight + KV Quantization", "• FP8: Hopper/Blackwell default\n• AWQ INT4: 35GB 70B weights\n  (pair with FP8 KV cache!)", LIB_SD, 6, stroke="#047857", bg="#ecfdf5")
lib_node(els13, "is_ec", 710, 365, 292, 135, "Serving Break-Even Math", "• Bursty <35% util -> Token API\n• Steady >45% util -> vLLM/SGLang\n• <200ms voice -> Custom LPU", LIB_SW, 6, stroke="#b45309", bg="#fffbeb")
arrow(els13, "ais4", 350, 432, 383, 432)
arrow(els13, "ais5", 677, 432, 710, 432)


# ==============================================================================
# DIAGRAM 14: 13-codebase-rag-and-tradeoffs.excalidraw
# ==============================================================================
els14 = []
els14.append(text_el("ct_title", 40, 18, 980, 34, "AI System Design Trade-Offs: Multi-Repo Code Search, <100ms Scoring & Ship Gates", size=22, family=2))
els14.append(text_el("ct_sub", 40, 52, 980, 22, "Tree-Sitter AST + Call Graph  •  <60s Webhook Diff  •  Point-in-Time Features  •  Contamination & KL Gates", size=13, family=3, color="#475569"))

container(els14, "ct_c1", 40, 90, 980, 205, "1. MULTI-REPO CODEBASE SEARCH & COPILOT INDEXER (10,000 REPOS, <60S PUSH FRESHNESS)", stroke="#1d4ed8", dash="solid")
lib_node(els14, "ct_as", 56, 135, 218, 135, "1. AST Diff Hook", "Git push -> Tree-sitter\nFunction/class spans\nRe-embeds <60s diff", LIB_SD, 18, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els14, "ct_ix", 296, 135, 224, 135, "2. 3-Modal + Graph", "Code emb + BM25 (4x sym)\nCached NL summary\nCross-repo call graph", LIB_SD, 9, stroke="#047857", bg="#ecfdf5")
lib_node(els14, "ct_rr", 542, 135, 224, 135, "3. Rerank + Filter", "Down-weight codegen\nGraph hop expansion\nCross-encode 50 -> 10", LIB_SW, 6, stroke="#b45309", bg="#fffbeb")
lib_node(els14, "ct_vf", 788, 135, 214, 135, "4. Span Verifier", "Cite repo:file:L10-L28\nCheck span @ commit\nDrop uncited claims", LIB_SD, 16, stroke="#6d28d9", bg="#f5f3ff")
arrow(els14, "act1", 274, 202, 296, 202)
arrow(els14, "act2", 520, 202, 542, 202)
arrow(els14, "act3", 766, 202, 788, 202)

container(els14, "ct_c2", 40, 320, 980, 205, "2. <100MS REAL-TIME SCORING, EXPLORATION HOLDOUTS & CONTENT-ADDRESSED SHIP GATES", stroke="#b45309", dash="solid")
lib_node(els14, "ct_on", 56, 365, 294, 135, "1. <100ms Online Cascade", "• Little's Law: L = λ * W\n• <5ms Redis point-in-time feat\n• <35ms SLM -> rule fallback", LIB_SW, 2, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els14, "ct_fb", 383, 365, 294, 135, "2. Anti-Poisoning Holdout", "• Blocked items lack labels!\n• 1-2% exploration pass-through\n• Logs serving features (0 skew)", LIB_SW, 1, stroke="#dc2626", bg="#fef2f2")
lib_node(els14, "ct_sg", 710, 365, 292, 135, "3. Model & Eval Ship Gate", "• Hash-chained stage manifest\n• 13-gram (<0.1%) leak check\n• Regression + KL drift cap", LIB_SD, 6, stroke="#047857", bg="#ecfdf5")
arrow(els14, "act4", 350, 432, 383, 432)
arrow(els14, "act5", 677, 432, 710, 432)


# ==============================================================================
# DIAGRAM 15: 14-flagship-ai-designs.excalidraw
# ==============================================================================
els15 = []
els15.append(text_el("fa_title", 40, 18, 980, 34, "Flagship AI System Designs: Web Answer Engine, PR Code Reviewer & Doc VLM", size=22, family=2))
els15.append(text_el("fa_sub", 40, 52, 980, 22, "Fresh Crawl + Singleflight  •  AST Caller Expansion & >85% Critic Gate  •  ColPali BBox Provenance", size=13, family=3, color="#475569"))

container(els15, "fa_c1", 40, 90, 980, 205, "1. WEB-SCALE AI ANSWER ENGINE (PERPLEXITY / SEARCHGPT — <1.2S TTFT, INLINE CITATIONS)", stroke="#1d4ed8", dash="solid")
lib_node(els15, "fa_qr", 56, 135, 218, 135, "1. Query Router", "Fresh (<60s) vs static\n3-5 parallel rewrites\nSingleflight hot cache", LIB_SD, 16, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els15, "fa_wi", 296, 135, 224, 135, "2. Tiered Web Index", "RAM news tier (<60s)\nSSD BM25 + HNSW shards\nSEO/injection shield", LIB_SD, 9, stroke="#047857", bg="#ecfdf5")
lib_node(els15, "fa_ps", 542, 135, 224, 135, "3. Passage Scorer", "Slice 300-tok windows\nFast cross-encoder\nTop 80 -> 10 (<90 ms)", LIB_SD, 18, stroke="#b45309", bg="#fffbeb")
lib_node(els15, "fa_cs", 788, 135, 214, 135, "4. Cited Streamer", "Stream [url_id] claims\nNLI span grounding\nFollow-up chips", LIB_SD, 23, stroke="#6d28d9", bg="#f5f3ff")
arrow(els15, "afa1", 274, 202, 296, 202)
arrow(els15, "afa2", 520, 202, 542, 202)
arrow(els15, "afa3", 766, 202, 788, 202)

container(els15, "fa_c2", 40, 320, 980, 205, "2. AUTONOMOUS PR CODE-REVIEW BOT & MULTIMODAL DOCUMENT INTELLIGENCE PIPELINE", stroke="#047857", dash="solid")
lib_node(els15, "fa_pr", 56, 365, 294, 135, "AST-Expanded PR Reviewer", "• Expand +- diff -> AST callers\n• SAST/lint first, LLM second\n• >85% critic gate (<10% noise!)", LIB_SW, 4, stroke="#1d4ed8", bg="#eff6ff")
lib_node(els15, "fa_hk", 383, 365, 294, 135, "Incremental Hunk Dedupe", "• Hash (file, ast_sym, hunk)\n• Re-review only new push delta\n• Track resolved-by-commit KPI", LIB_SD, 6, stroke="#047857", bg="#ecfdf5")
lib_node(els15, "fa_dc", 710, 365, 292, 135, "Multimodal Doc VLM Pipe", "• Clean PDF -> fast text lane\n• Tables/charts -> VLM/ColPali\n• (page, bbox) visual citations", LIB_SD, 7, stroke="#6d28d9", bg="#f5f3ff")
arrow(els15, "afa4", 350, 432, 383, 432)
arrow(els15, "afa5", 677, 432, 710, 432)

diagrams = {
    "01-kafka-and-redis.excalidraw": els1,
    "02-database-sharding-keys.excalidraw": els2,
    "03-notification-system.excalidraw": els3,
    "03-core-case-studies.excalidraw": els4,
    "04-rag-and-agents.excalidraw": els5,
    "05-agent-loops-memory.excalidraw": els6,
    "06-mcp-evals-reactive.excalidraw": els7,
    "07-durable-agent-runtime.excalidraw": els8,
    "08-agent-case-studies.excalidraw": els9,
    "09-prompt-decoding-lora.excalidraw": els10,
    "10-agent-harness-and-skills.excalidraw": els11,
    "11-multimodal-cua-and-voice.excalidraw": els12,
    "12-llm-inference-serving.excalidraw": els13,
    "13-codebase-rag-and-tradeoffs.excalidraw": els14,
    "14-flagship-ai-designs.excalidraw": els15,
    # Keep mock0-notification-system.excalidraw synced so existing links never break
    "mock0-notification-system.excalidraw": els3,
}

for fname, elements in diagrams.items():
    out_path = os.path.join(DIAG_DIR, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(make_scene(elements), f, indent=2)
    print(f"Wrote {fname} ({len(elements)} elements, including System Design Library blocks)")
