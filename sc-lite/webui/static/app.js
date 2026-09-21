/* SC Lite Control — fleet + single miner UI */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    view: "fleet",
    miners: [],
    selected: new Set(),
    detailId: null,
    detail: null,
    timer: null,
    profiles: {},
    fanDefaults: {},
    demo: false,
  };

  function toast(msg, err = false) {
    const el = $("toast");
    el.textContent = typeof msg === "string" ? msg : JSON.stringify(msg, null, 2);
    el.classList.toggle("err", !!err);
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove("show"), 5000);
  }

  async function api(method, path, body) {
    const opts = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }

  function fmtHs(mhs) {
    if (mhs == null || Number.isNaN(Number(mhs))) return "—";
    const n = Number(mhs);
    // Goldshell reports large "MHS" totals — show TH/s when huge
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)} TH/s`;
    if (n >= 1000) return `${(n / 1000).toFixed(2)} GH/s`;
    return `${n.toFixed(1)} MH/s`;
  }
  function fmtTemp(t) {
    return t == null ? "—" : `${Number(t).toFixed(1)}°C`;
  }
  function fmtFan(f) {
    return f == null ? "—" : `${Math.round(Number(f))} RPM`;
  }
  function fmtAgo(ts) {
    if (!ts) return "never";
    const age = Date.now() / 1000 - Number(ts);
    if (age < 0) return `ts=${ts}`;
    if (age < 60) return `${Math.floor(age)}s`;
    if (age < 3600) return `${Math.floor(age / 60)}m`;
    return `${(age / 3600).toFixed(1)}h`;
  }
  function fmtUp(s) {
    if (s == null) return "—";
    s = Number(s);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
  }

  function setView(v) {
    state.view = v;
    const map = {
      fleet: ["viewFleet", "tabFleet"],
      detail: ["viewDetail", "tabDetail"],
      batch: ["viewBatch", "tabBatch"],
      settings: ["viewSettings", "tabSettings"],
    };
    Object.keys(map).forEach((name) => {
      const [vid, tid] = map[name];
      const view = $(vid);
      const tab = $(tid);
      if (view) view.classList.toggle("hidden", v !== name);
      if (tab) tab.classList.toggle("active", v === name);
    });
  }

  function renderFleet() {
    const grid = $("fleetGrid");
    if (!grid) return;
    try {
    if (!state.miners.length) {
      grid.innerHTML = `<div class="panel muted">No miners in registry. Add one above (or edit <code>miners.json</code>).</div>`;
      return;
    }
    grid.innerHTML = state.miners
      .map((m) => {
        const s = m.snapshot || {};
        const ok = !!s.ok;
        const checked = state.selected.has(m.id) ? "checked" : "";
        const wp = s.working_pool;
        const prefAlive = (s.pools || []).find((p) => Number(p.id) === 0);
        const sticky =
          ok &&
          prefAlive &&
          prefAlive.status === "Alive" &&
          wp &&
          Number(wp.id) !== 0;
        const fc = m.fan_control || {};
        const fr = m.fan_runtime || {};
        const fanOn = !!fc.enabled;
        const prof = fc.profile || state.fanDefaults.profile || "steps-default";
        const profOpts = Object.keys(state.profiles || {})
          .map(
            (k) =>
              `<option value="${escapeHtml(k)}" ${k === prof ? "selected" : ""}>${escapeHtml(
                (state.profiles[k] && state.profiles[k].label) || k
              )}</option>`
          )
          .join("");
        return `
        <div class="card ${state.selected.has(m.id) ? "selected" : ""}" data-id="${m.id}">
          <div class="row">
            <input type="checkbox" class="sel" data-id="${m.id}" ${checked} />
            <h3 style="flex:1;cursor:pointer" class="open" data-id="${m.id}">${escapeHtml(m.name || m.id)}</h3>
            <span class="pill ${ok ? "ok" : "bad"}">${ok ? "online" : "down"}</span>
            ${sticky ? `<span class="pill warn">sticky P${wp.id}</span>` : ""}
            ${fanOn ? `<span class="pill ok">auto-fan</span>` : `<span class="pill">fan off</span>`}
          </div>
          <div class="meta">${escapeHtml(m.ip)}</div>
          <div class="kv">
            <div><div class="label">Hashrate</div><div class="value">${fmtHs(s.mhs_av)}</div></div>
            <div><div class="label">Temp max</div><div class="value">${fmtTemp(s.temp_max)}</div></div>
            <div><div class="label">Fans avg</div><div class="value">${fmtFan(s.fan_avg)}</div></div>
            <div><div class="label">Uptime</div><div class="value">${fmtUp(s.elapsed)}</div></div>
            <div style="grid-column:1/-1">
              <div class="label">Working pool</div>
              <div class="value" style="font-size:0.8rem;word-break:break-all">
                ${wp ? `P${wp.id} · ${escapeHtml(wp.url || "")}` : "—"}
              </div>
            </div>
            <div style="grid-column:1/-1">
              <div class="label">Auto fan</div>
              <div class="value" style="font-size:0.75rem">${escapeHtml(fr.last_status || "—")}
                ${fr.last_applied_fan != null ? ` · plan ${fr.last_applied_fan}` : ""}
                ${fc.fan_offset ? ` · offset ${fc.fan_offset}` : ""}
              </div>
            </div>
          </div>
          <div class="row gap">
            <label class="muted"><input type="checkbox" class="fan-en" data-id="${m.id}" ${fanOn ? "checked" : ""}/> auto fan</label>
            <select class="fan-prof" data-id="${m.id}">${profOpts}</select>
          </div>
          <div class="row gap">
            <button type="button" class="fan-minus" data-id="${m.id}">Fan −5</button>
            <button type="button" class="fan-plus" data-id="${m.id}">Fan +5</button>
            <button type="button" class="open primary" data-id="${m.id}">Open</button>
            <button type="button" class="failback" data-id="${m.id}">Failback</button>
          </div>
        </div>`;
      })
      .join("");

    grid.querySelectorAll(".sel").forEach((el) => {
      el.addEventListener("change", () => {
        if (el.checked) state.selected.add(el.dataset.id);
        else state.selected.delete(el.dataset.id);
        renderFleet();
      });
    });
    grid.querySelectorAll(".open").forEach((el) => {
      el.addEventListener("click", () => openDetail(el.dataset.id));
    });
    grid.querySelectorAll(".failback").forEach((el) => {
      el.addEventListener("click", async () => {
        try {
          toast(await api("POST", `/api/miners/${el.dataset.id}/action/failback`, { preferred: 0, soft_restart: true }));
          await refreshOne(el.dataset.id);
        } catch (e) {
          toast(String(e.message || e), true);
        }
      });
    });
    grid.querySelectorAll(".fan-minus").forEach((el) => {
      el.addEventListener("click", () => nudgeFan(el.dataset.id, -5));
    });
    grid.querySelectorAll(".fan-plus").forEach((el) => {
      el.addEventListener("click", () => nudgeFan(el.dataset.id, 5));
    });
    grid.querySelectorAll(".fan-en").forEach((el) => {
      el.addEventListener("change", async () => {
        try {
          await api("POST", `/api/miners/${el.dataset.id}/fan_control`, { enabled: el.checked });
          toast(`Auto fan ${el.checked ? "ON" : "OFF"} · ${el.dataset.id}`);
          await refreshFleetList();
        } catch (e) {
          toast(String(e.message || e), true);
        }
      });
    });
    grid.querySelectorAll(".fan-prof").forEach((el) => {
      el.addEventListener("change", async () => {
        try {
          await api("POST", `/api/miners/${el.dataset.id}/fan_control`, { profile: el.value });
          toast(`Profile ${el.value} · ${el.dataset.id}`);
          await refreshFleetList();
        } catch (e) {
          toast(String(e.message || e), true);
        }
      });
    });
    } catch (e) {
      console.error(e);
      grid.innerHTML = `<div class="panel" style="color:var(--bad)">Render error: ${escapeHtml(e.message || e)}</div>`;
    }
  }

  async function nudgeFan(id, delta) {
    try {
      const j = await api("POST", `/api/miners/${id}/fan_nudge`, { delta });
      toast(`Fan → ${j.fan}`);
      await refreshOne(id);
      await refreshFleetList();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  }

  function fillProfileSelects() {
    const sel = $("fanProfileDefault");
    if (!sel) return;
    const cur = state.fanDefaults.profile || "steps-default";
    sel.innerHTML = Object.keys(state.profiles || {})
      .map(
        (k) =>
          `<option value="${escapeHtml(k)}" ${k === cur ? "selected" : ""}>${escapeHtml(
            (state.profiles[k] && state.profiles[k].label) || k
          )}</option>`
      )
      .join("");
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function refreshFleetList() {
    const j = await api("GET", "/api/miners");
    state.miners = j.miners || [];
    state.profiles = j.profiles || {};
    state.fanDefaults = j.fan_defaults || {};
    state.demo = !!j.demo;
    const dt = $("demoToggle");
    if (dt) dt.checked = state.demo;
    fillProfileSelects();
    const hint = $("fanRuntimeHint");
    if (hint) {
      const bits = state.miners.map((m) => {
        const fr = m.fan_runtime || {};
        const on = m.fan_control && m.fan_control.enabled;
        return `${m.id}: ${on ? "ON" : "off"} ${fr.last_status || ""}`;
      });
      hint.textContent = bits.join(" · ") || "No miners";
    }
    renderFleet();
  }

  async function refreshAllSnapshots() {
    $("btnRefresh").disabled = true;
    try {
      await refreshFleetList(); // keeps demo rows + fan meta
      const j = await api("GET", "/api/fleet/refresh");
      const map = j.miners || {};
      state.miners = state.miners.map((m) => ({
        ...m,
        snapshot: map[m.id] || m.snapshot,
      }));
      renderFleet();
      if (state.detailId && map[state.detailId]) {
        state.detail = map[state.detailId];
        renderDetail();
      }
    } catch (e) {
      toast(String(e.message || e), true);
    } finally {
      $("btnRefresh").disabled = false;
    }
  }

  async function refreshOne(id) {
    const snap = await api("GET", `/api/miners/${id}/snapshot`);
    state.miners = state.miners.map((m) => (m.id === id ? { ...m, snapshot: snap } : m));
    if (state.detailId === id) {
      state.detail = snap;
      renderDetail();
    }
    renderFleet();
    return snap;
  }

  async function openDetail(id) {
    state.detailId = id;
    setView("detail");
    $("detailTitle").textContent = id;
    try {
      state.detail = await refreshOne(id);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  }

  function renderDetail() {
    const s = state.detail || {};
    $("detailTitle").textContent = `${s.name || state.detailId} · ${s.ip || ""}`;
    const pill = $("detailPill");
    pill.textContent = s.ok ? "online" : "down";
    pill.className = `pill ${s.ok ? "ok" : "bad"}`;

    const kv = $("detailKv");
    kv.innerHTML = [
      ["Hashrate", fmtHs(s.mhs_av)],
      ["Temp max", fmtTemp(s.temp_max)],
      ["Fans avg", fmtFan(s.fan_avg)],
      ["Uptime", fmtUp(s.elapsed)],
      ["Accepted", s.accepted ?? "—"],
      ["Rejected", s.rejected ?? "—"],
      ["HW errors", s.hw ?? "—"],
      ["Tempcontrol", s.tempcontrol == null ? "—" : String(s.tempcontrol)],
    ]
      .map(
        ([label, value]) =>
          `<div><div class="label">${label}</div><div class="value">${value}</div></div>`
      )
      .join("");

    const boards = $("detailBoards");
    if (!s.devs || !s.devs.length) boards.innerHTML = `<span class="muted">${s.error || s.jwt_error || "no board data"}</span>`;
    else {
      boards.innerHTML = `<table><thead><tr><th>ID</th><th>Status</th><th>Temp</th><th>MHS</th><th>Fans</th></tr></thead><tbody>${s.devs
        .map(
          (d) =>
            `<tr><td>${d.id}</td><td>${d.status}</td><td>${fmtTemp(d.temp)}</td><td>${fmtHs(d.mhs)}</td><td class="mono">${escapeHtml(d.fans || "")}</td></tr>`
        )
        .join("")}</tbody></table>`;
    }

    if (s.plan) {
      $("detailPlanRaw").textContent = s.plan.raw || "—";
      if (s.plan.mhz != null) $("planMhz").value = s.plan.mhz;
      if (s.plan.mv != null) $("planMv").value = s.plan.mv;
      if (s.plan.pv != null) $("planPv").value = s.plan.pv;
      if (s.plan.fan_a != null) {
        $("detailFan").value = s.plan.fan_a;
        $("detailFanVal").textContent = s.plan.fan_a;
      }
    }
    if (s.tempcontrol != null) $("detailTc").checked = !!s.tempcontrol;

    const body = $("poolsBody");
    const workingId = s.working_pool ? Number(s.working_pool.id) : null;
    const pools = s.pools || [];
    body.innerHTML = pools
      .map((p) => {
        const work = workingId === Number(p.id) ? "YES" : "";
        return `<tr>
          <td>P${p.id}</td>
          <td>${escapeHtml(p.status)}</td>
          <td>${work}</td>
          <td>${p.accepted ?? ""}</td>
          <td class="mono" style="font-size:0.78rem;word-break:break-all">${escapeHtml(p.url)}<br/>${escapeHtml(p.user)} · last ${fmtAgo(p.last_share)}</td>
          <td><button type="button" class="danger delpool" data-idx="${p.id}">Del</button></td>
        </tr>`;
      })
      .join("");

    body.querySelectorAll(".delpool").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const httpPools = s.http_pools;
        let poolObj = null;
        if (Array.isArray(httpPools)) {
          poolObj = httpPools.find((x) => Number(x["pool-priority"]) === Number(btn.dataset.idx) || Number(x.dragid) === Number(btn.dataset.idx));
          if (!poolObj) poolObj = httpPools[Number(btn.dataset.idx)];
        }
        if (!poolObj) {
          toast("Reload pools (need JWT http_pools) then delete", true);
          return;
        }
        if (!confirm(`Delete pool ${poolObj.url}?`)) return;
        try {
          toast(await api("POST", `/api/miners/${state.detailId}/action/del_pool`, { pool: poolObj }));
          await refreshOne(state.detailId);
        } catch (e) {
          toast(String(e.message || e), true);
        }
      });
    });
  }

  // wire UI
  $("tabFleet").onclick = () => setView("fleet");
  $("tabDetail").onclick = () => {
    if (state.detailId) setView("detail");
    else toast("Open a miner from Fleet first", true);
  };
  $("tabBatch").onclick = () => setView("batch");
  $("tabSettings").onclick = () => setView("settings");
  $("btnBackFleet").onclick = () => setView("fleet");
  $("btnRefresh").onclick = () => refreshAllSnapshots();
  $("fleetFan").oninput = () => ($("fleetFanVal").textContent = $("fleetFan").value);
  $("detailFan").oninput = () => ($("detailFanVal").textContent = $("detailFan").value);

  $("btnSelectAll").onclick = () => {
    state.miners.forEach((m) => state.selected.add(m.id));
    renderFleet();
  };
  $("btnSelectNone").onclick = () => {
    state.selected.clear();
    renderFleet();
  };

  $("btnAddMiner").onclick = async () => {
    try {
      await api("POST", "/api/miners", {
        id: $("addId").value.trim(),
        name: $("addName").value.trim(),
        ip: $("addIp").value.trim(),
        password: $("addPass").value,
      });
      toast("Miner added");
      await refreshFleetList();
      await refreshAllSnapshots();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };

  async function fleetAction(action, extra = {}) {
    const ids = [...state.selected];
    if (!ids.length) {
      toast("Select at least one miner", true);
      return;
    }
    try {
      const j = await api("POST", "/api/fleet/action", { action, ids, ...extra });
      toast(j);
      await refreshAllSnapshots();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  }

  $("btnFleetFan").onclick = () => fleetAction("fan", { fan: Number($("fleetFan").value) });
  $("btnFleetFanMinus").onclick = () => {
    const ids = [...state.selected];
    if (!ids.length) return toast("Select miners", true);
    ids.forEach((id) => nudgeFan(id, -5));
  };
  $("btnFleetFanPlus").onclick = () => {
    const ids = [...state.selected];
    if (!ids.length) return toast("Select miners", true);
    ids.forEach((id) => nudgeFan(id, 5));
  };
  $("btnFleetTc").onclick = () =>
    fleetAction("tempcontrol", { enabled: $("fleetTc").checked });

  $("btnSaveFanDefaults").onclick = async () => {
    try {
      await api("POST", "/api/fan/defaults", {
        profile: $("fanProfileDefault").value,
      });
      toast("Fan defaults saved");
      await refreshFleetList();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnFanEnableSelected").onclick = async () => {
    const ids = [...state.selected];
    if (!ids.length) return toast("Select miners", true);
    for (const id of ids) {
      await api("POST", `/api/miners/${id}/fan_control`, {
        enabled: true,
        profile: $("fanProfileDefault").value,
      });
    }
    toast("Auto fan enabled on selected");
    await refreshFleetList();
  };
  $("btnFanDisableSelected").onclick = async () => {
    const ids = [...state.selected];
    if (!ids.length) return toast("Select miners", true);
    for (const id of ids) {
      await api("POST", `/api/miners/${id}/fan_control`, { enabled: false });
    }
    toast("Auto fan disabled on selected");
    await refreshFleetList();
  };
  $("btnFanApplyProfileSelected").onclick = async () => {
    const ids = [...state.selected];
    if (!ids.length) return toast("Select miners", true);
    const profile = $("fanProfileDefault").value;
    for (const id of ids) {
      await api("POST", `/api/miners/${id}/fan_control`, { profile });
    }
    await api("POST", "/api/fan/defaults", { profile });
    toast(`Profile ${profile} applied`);
    await refreshFleetList();
  };
  $("btnFleetFailback").onclick = () => {
    if (!confirm("Failback selected miners to P0 + soft restart?")) return;
    fleetAction("failback", { preferred: 0, soft_restart: true });
  };
  $("btnFleetRestart").onclick = () => {
    if (!confirm("Soft-restart selected miners?")) return;
    fleetAction("restart");
  };

  $("btnBatchAddPool").onclick = () => {
    const url = $("batchPoolUrl").value.trim();
    const payout = $("batchPayout").value.trim();
    if (!url || !payout) {
      toast("URL and payout address required", true);
      return;
    }
    fleetAction("add_pool", {
      url,
      payout,
      pass: $("batchPoolPass").value.trim() || "x",
      keep_worker: $("batchKeepWorker").checked,
      worker: $("batchWorker").value.trim(),
      make_preferred: $("batchMakePreferred").checked,
      soft_restart: $("batchAddRestart").checked,
    });
  };

  $("btnBatchOrder").onclick = () => {
    const raw = $("batchOrder").value.trim();
    if (!raw) {
      toast("Order required, e.g. 1,0", true);
      return;
    }
    const order = raw.split(/[,\s]+/).filter(Boolean).map((x) => {
      if (/^\d+$/.test(x)) return Number(x);
      return x;
    });
    fleetAction("set_pool_order", {
      order,
      soft_restart: $("batchOrderRestart").checked,
    });
  };

  $("btnBatchDelPool").onclick = () => {
    const url = $("batchDelUrl").value.trim();
    if (!url) {
      toast("URL required", true);
      return;
    }
    if (!confirm(`Remove pool matching "${url}" from selected miners?`)) return;
    fleetAction("del_pool", { url });
  };

  $("btnBatchPromote").onclick = () => {
    const url = $("batchPrefUrl").value.trim();
    if (!url) {
      toast("URL required", true);
      return;
    }
    if (!confirm(`Promote "${url}" to preferred on selected miners?`)) return;
    fleetAction("make_preferred", {
      url,
      soft_restart: $("batchPromoteRestart").checked,
    });
  };

  $("btnDetailFan").onclick = async () => {
    try {
      toast(await api("POST", `/api/miners/${state.detailId}/action/fan`, { fan: Number($("detailFan").value) }));
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnDetailTc").onclick = async () => {
    try {
      toast(await api("POST", `/api/miners/${state.detailId}/action/tempcontrol`, { enabled: $("detailTc").checked }));
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnDetailPlan").onclick = async () => {
    try {
      toast(
        await api("POST", `/api/miners/${state.detailId}/action/plan`, {
          mhz: $("planMhz").value ? Number($("planMhz").value) : undefined,
          mv: $("planMv").value ? Number($("planMv").value) : undefined,
          pv: $("planPv").value ? Number($("planPv").value) : undefined,
          fan: Number($("detailFan").value),
          manual: true,
        })
      );
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnDetailRestart").onclick = async () => {
    if (!confirm("Soft restart this miner?")) return;
    try {
      toast(await api("POST", `/api/miners/${state.detailId}/action/restart`, {}));
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnFailback").onclick = async () => {
    if (!confirm("Failback to preferred + soft restart?")) return;
    try {
      toast(
        await api("POST", `/api/miners/${state.detailId}/action/failback`, {
          preferred: Number($("preferredIdx").value || 0),
          soft_restart: true,
        })
      );
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnReloadPools").onclick = () => refreshOne(state.detailId);
  $("btnAddPool").onclick = async () => {
    try {
      toast(
        await api("POST", `/api/miners/${state.detailId}/action/add_pool`, {
          url: $("poolUrl").value.trim(),
          user: $("poolUser").value.trim(),
          pass: $("poolPass").value.trim() || "x",
        })
      );
      await refreshOne(state.detailId);
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };
  $("btnRemoveMiner").onclick = async () => {
    if (!confirm("Remove this miner from local registry only?")) return;
    try {
      await api("DELETE", `/api/miners/${state.detailId}`);
      state.detailId = null;
      setView("fleet");
      await refreshFleetList();
      await refreshAllSnapshots();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };

  function armTimer() {
    clearInterval(state.timer);
    if ($("autoRefresh").checked) {
      state.timer = setInterval(() => refreshAllSnapshots(), 5000);
    }
  }
  $("btnDemoSave").onclick = async () => {
    try {
      await api("POST", "/api/settings/demo", { demo: $("demoToggle").checked });
      toast($("demoToggle").checked ? "Demo miners ON" : "Demo miners OFF");
      await refreshFleetList();
      await refreshAllSnapshots();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  };

  let lastProbe = null;
  $("btnProbe").onclick = async () => {
    const ip = $("probeIp").value.trim();
    if (!ip) return toast("IP required", true);
    $("btnProbe").disabled = true;
    $("probeOut").textContent = "Probing…";
    try {
      lastProbe = await api("POST", "/api/probe", {
        ip,
        password: $("probePass").value,
        try_common_passwords: $("probeTryCommon").checked,
        add_to_registry: $("probeAdd").checked,
      });
      const id = lastProbe.identity || {};
      const dialect = lastProbe.dialect || {};
      const caps = lastProbe.capabilities || {};
      $("probeOut").textContent = [
        `ok=${lastProbe.ok}  profile=${id.suggested_profile}  model=${id.model || "?"}  fw=${id.firmware || "?"}`,
        `ports: 80=${lastProbe.ports && lastProbe.ports["80"]}  4028=${lastProbe.ports && lastProbe.ports["4028"]}  ssh=${lastProbe.ports && lastProbe.ports["22"]}`,
        `plan: ${dialect.raw || "(none)"}`,
        `dialect: sc_lite=${dialect.parseable_sc_lite_int_v}  hs_box=${dialect.parseable_hs_box_float_v}`,
        `notes: ${(dialect.notes || []).join("; ")}`,
        `fan_kick_likely=${caps.fan_kick_likely}  known_family=${id.known_family}`,
        lastProbe.registry ? `registry: ${JSON.stringify(lastProbe.registry)}` : "",
        lastProbe.error ? `error: ${lastProbe.error}` : "",
      ]
        .filter(Boolean)
        .join("\n");
      $("btnProbeCopyIssue").disabled = !lastProbe.github_issue_markdown;
      if (lastProbe.registry && lastProbe.registry.added) {
        await refreshFleetList();
        await refreshAllSnapshots();
      }
      toast(`Probe done · ${id.suggested_profile || "unknown"}`);
    } catch (e) {
      $("probeOut").textContent = String(e.message || e);
      toast(String(e.message || e), true);
    } finally {
      $("btnProbe").disabled = false;
    }
  };
  $("btnProbeCopyIssue").onclick = async () => {
    if (!lastProbe || !lastProbe.github_issue_markdown) return;
    try {
      await navigator.clipboard.writeText(lastProbe.github_issue_markdown);
      toast("GitHub issue markdown copied");
    } catch (e) {
      // fallback
      const ta = document.createElement("textarea");
      ta.value = lastProbe.github_issue_markdown;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("GitHub issue markdown copied");
    }
  };

  $("btnDetailFanMinus").onclick = () => {
    if (state.detailId) nudgeFan(state.detailId, -5);
  };
  $("btnDetailFanPlus").onclick = () => {
    if (state.detailId) nudgeFan(state.detailId, 5);
  };

  $("autoRefresh").onchange = armTimer;

  (async () => {
    await refreshFleetList();
    await refreshAllSnapshots();
    armTimer();
  })();
})();
