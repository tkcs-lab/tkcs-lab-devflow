// Board rules: pure functions shared by the board page and its tests (no DOM, no clock).
// Records are tld status records; nowMs is a millisecond timestamp.
var TLD_DAY_MS = 24 * 60 * 60 * 1000;

// Whole minutes from the ISO instant fromIso to nowMs (negative when fromIso is later).
function elapsed(fromIso, nowMs) {
  return Math.floor((nowMs - Date.parse(fromIso)) / 60000);
}

// Auto-hidden: needs_you is not true and updated_at is more than 7 days old.
function isHidden(rec, nowMs) {
  return rec.needs_you !== true && nowMs - Date.parse(rec.updated_at) > 7 * TLD_DAY_MS;
}

// Silent badge: a timer is armed, the record is not waiting on the owner or a PR, and the
// heartbeat is overdue by more than twice max(next_check_at - updated_at, 5 min).
function isSilent(rec, nowMs) {
  if (rec.next_check_at === null || rec.next_check_at === undefined) return false;
  if (rec.status === "waiting_user" || rec.status === "pr_open" || rec.status === "done") return false;
  var interval = Math.max(elapsed(rec.updated_at, Date.parse(rec.next_check_at)), 5);
  return elapsed(rec.updated_at, nowMs) > 2 * interval;
}

// The one section a record is shown in: needs_you, pr_open, done, running or hidden.
function section(rec, nowMs) {
  if (rec.needs_you === true) return "needs_you";
  if (isHidden(rec, nowMs)) return "hidden";
  if (rec.status === "pr_open") return "pr_open";
  if (rec.finished_at && nowMs - Date.parse(rec.finished_at) <= 7 * TLD_DAY_MS) return "done";
  if (rec.status === "done" || rec.status === "failed") return "hidden";
  return "running";
}

// Drift indicator of one phase (count only; the paths are in the pull request description):
// null when no scope was recorded or nothing drifted, else {text, title, level}.
function drift(phase) {
  var s = phase && phase.scope;
  if (!s || typeof s !== "object") return null;
  if (s.check !== "ok") return { text: "scope ?", title: "scope check unavailable", level: "unknown" };
  var n = s.out_of_scope_count, c = s.collision_count;
  if (!n) return null;
  var title = n + " file" + (n === 1 ? "" : "s") + " outside touches";
  if (c) title += ", " + c + " in another phase's touches";
  if (s.disposition === "reverted") title += "; reverted later";
  else if (s.disposition === "partly_reverted") title += "; partly reverted later";
  return { text: "drift " + n, title: title, level: c ? "collision" : "drift" };
}

// Owner dismissal: the entry carries a dismissed_at made on its current version (any state).
function isDismissed(entry) {
  return typeof entry.dismissed_at === "string";
}

// An ask belongs to an entry by its record field, else by session and project.
function linksTo(ask, entry) {
  if (typeof ask.record === "string") return ask.record === entry.id;
  var session = entry.data.orchestrator_session;
  return typeof session === "string" && session !== "" &&
    ask.created_by === session && ask.project === entry.data.project;
}

function linkedAsks(entry, asks) {
  return asks.filter(function (ask) { return linksTo(ask, entry); });
}

// The answered linked ask that arrived since the entry began waiting (none open), else null.
function answerReceived(entry, asks) {
  var linked = linkedAsks(entry, asks);
  if (linked.some(function (ask) { return ask.state === "open"; })) return null;
  var since = Date.parse(entry.data.needs_you_since);
  for (var i = 0; i < linked.length; i++) {
    if (linked[i].state === "answered" && Date.parse(linked[i].answered_at) >= since) return linked[i];
  }
  return null;
}

// Hand-over of a finished make-plan record (the same rules as tld.board.record.handover_errors).
var HANDOVER_REF_PATH = "[A-Za-z0-9._/-]+";
var HANDOVER_URL_MAX = 300;
var HANDOVER_PREFIXES = ["/tld:implement", "implement"];

function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

// The links of a record's hand-over that are set and pass the rules: [{name, url}] in the order issue, plan, spec.
function handoverLinks(rec) {
  var h = rec && rec.handover;
  if (!h || typeof h !== "object" || typeof rec.repo !== "string") return [];
  var base = "^https://github\\.com/" + escapeRe(rec.repo);
  var slug = typeof h.plan_slug === "string" && /^[a-z0-9][a-z0-9-]{0,79}$/.test(h.plan_slug) ? escapeRe(h.plan_slug) : null;
  var shapes = [
    ["issue", h.issue_url, new RegExp(base + "/issues/[1-9][0-9]{0,9}$")],
    ["plan", h.plan_url, new RegExp(base + "/blob/" + HANDOVER_REF_PATH + "\\.md$")],
    ["spec", h.spec_url, new RegExp(base + "/tree/" + HANDOVER_REF_PATH + "/openspec/changes/" + (slug === null ? HANDOVER_REF_PATH : slug) + "$")],
  ];
  var out = [];
  shapes.forEach(function (sh) {
    var url = sh[1];
    if (typeof url !== "string" || url.length > HANDOVER_URL_MAX || !sh[2].test(url)) return;
    var bad = url.slice("https://github.com/".length).split("/").some(function (seg) {
      return seg === "" || seg === "." || seg === "..";
    });
    if (!bad) out.push({ name: sh[0], url: url });
  });
  return out;
}

// The command to copy: only a fixed prefix plus a plan link that handoverLinks accepted, else null.
function handoverCommand(rec) {
  var h = rec && rec.handover;
  if (!h || typeof h.next_command !== "string") return null;
  var plan = handoverLinks(rec).filter(function (l) { return l.name === "plan"; })[0];
  if (!plan) return null;
  for (var i = 0; i < HANDOVER_PREFIXES.length; i++) {
    if (h.next_command === HANDOVER_PREFIXES[i] + " " + plan.url) return h.next_command;
  }
  return null;
}

// The Summary as parts [{label, text}]; a label line is "**Label:** text" (optionally after "- ").
function summaryParts(text) {
  var parts = [];
  String(text).split("\n").forEach(function (line) {
    if (line.trim() === "") return;
    var m = /^(?:- )?\*\*([A-Za-z ]{1,30}):\*\*\s?(.*)$/.exec(line);
    if (m) parts.push({ label: m[1], text: m[2] });
    else if (parts.length) parts[parts.length - 1].text += "\n" + line;
    else parts.push({ label: null, text: line });
  });
  return parts;
}

// A done make-plan record with a hand-over, in "Done", that no run of the same project and plan slug has overtaken.
function planReady(entry, entries, nowMs) {
  var rec = entry.data;
  if (rec.kind !== "command" || rec.command !== "make-plan" || rec.status !== "done") return false;
  if (!rec.handover || typeof rec.handover !== "object" || typeof rec.handover.plan_slug !== "string") return false;
  if (section(rec, nowMs) !== "done") return false;
  var finished = Date.parse(rec.finished_at);
  return !(entries || []).some(function (other) {
    var d = other.data;
    return d && d.kind === "run" && d.project === rec.project && d.plan_slug === rec.handover.plan_slug &&
      Date.parse(d.updated_at) >= finished;
  });
}

// Where an entry is drawn: {section, badge, ask}. section adds "linked" (no record card: the open ask is the card)
// and "ready" (a plan ready card, a sub-state of "done"). entries is the whole board, for planReady.
function place(entry, asks, nowMs, entries) {
  var rec = entry.data;
  if (isDismissed(entry)) return { section: "hidden", badge: "dismissed", ask: null };
  if (rec.needs_you === true) {
    var linked = linkedAsks(entry, asks);
    if (linked.some(function (ask) { return ask.state === "open"; })) return { section: "linked", badge: null, ask: null };
    var answered = answerReceived(entry, asks);
    if (answered) return { section: "running", badge: "answer_received", ask: answered };
  }
  var s = section(rec, nowMs);
  if (s === "done" && planReady(entry, entries || [], nowMs)) s = "ready";
  return { section: s, badge: null, ask: null };
}

// Usage page. A bar is drawn to 100% at most; above 100% of the limit it is marked over.
function usageBar(pct) { return { fill: Math.min(pct, 100), over: pct > 100 }; }

// The window still running: the one with the largest resets_at after nowSec, else null.
function usageNow(windows, nowSec) {
  var best = null;
  (windows || []).forEach(function (w) {
    if (w.resets_at > nowSec && (best === null || w.resets_at > best.resets_at)) best = w;
  });
  return best;
}

// Seconds as "just now", "<m> min" or "<h> h <m> min".
function usageAgo(seconds) {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return Math.floor(seconds / 60) + " min";
  var h = Math.floor(seconds / 3600);
  return h + " h " + Math.floor((seconds - h * 3600) / 60) + " min";
}

var USAGE_RANGE_DAYS = { five_hour: 30, seven_day: 56 };
var USAGE_MIN_WINDOWS = { five_hour: 6, seven_day: 2 };

// Would Standard have been enough? Counts the finished, busy windows lived on Max in the history range.
function usageVerdict(windows, kind, nowSec) {
  var from = nowSec - USAGE_RANGE_DAYS[kind] * 86400;
  var used = (windows || []).filter(function (w) {
    return w.complete === true && w.idle !== true && w.plan === "max" && w.resets_at >= from;
  });
  var n = used.length;
  var min = USAGE_MIN_WINDOWS[kind];
  if (n < min) return { kind: "few", text: "Not enough finished windows yet (" + n + " of " + min + " needed)." };
  var over = used.filter(function (w) { return w.over === true; });
  var pct = Math.round(over.length / n * 100);
  var peaks = used.map(function (w) { return w.peak_standard; }).sort(function (a, b) { return a - b; });
  var p90 = peaks[Math.ceil(0.9 * n) - 1];
  var result;
  if (over.length / n >= 0.25) {
    result = { kind: "max", text: "Max makes sense: Standard would have run out in " + over.length + " of " + n + " windows (" + pct + "%)." };
  } else if (over.length === 0 && p90 < 80) {
    result = { kind: "standard", text: "Standard would have been enough: it stayed below its limit in all " + n +
      " windows (busiest: " + Math.round(peaks[n - 1]) + "% of Standard)." };
  } else {
    result = { kind: "borderline", text: "Borderline: Standard would have run out in " + over.length + " of " + n + " windows (" + pct + "%)." };
  }
  if (over.length > 0) {
    var hours = 0;
    over.forEach(function (w) { hours += typeof w.blocked_hours === "number" ? w.blocked_hours : 0; });
    result.text += " Standard would have blocked you for at least " + hours.toFixed(1) + " h in total.";
  }
  return result;
}

// The issue page of a record's tracking issue (the same rules as tld.board.record), else null.
var ISSUE_MAX = 9999999999;
var ISSUE_REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
function issueUrl(rec) {
  if (!rec || typeof rec.repo !== "string" || !ISSUE_REPO.test(rec.repo)) return null;
  if (rec.repo.split("/").some(function (s) { return s === "." || s === ".."; })) return null;
  var n = rec.tracking_issue;
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > ISSUE_MAX) return null;
  return "https://github.com/" + rec.repo + "/issues/" + n;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { elapsed: elapsed, isHidden: isHidden, isSilent: isSilent, section: section, drift: drift,
    isDismissed: isDismissed, linksTo: linksTo, linkedAsks: linkedAsks, answerReceived: answerReceived, place: place,
    escapeRe: escapeRe, handoverLinks: handoverLinks, handoverCommand: handoverCommand, summaryParts: summaryParts, planReady: planReady,
    usageBar: usageBar, usageNow: usageNow, usageAgo: usageAgo, usageVerdict: usageVerdict, issueUrl: issueUrl };
}
