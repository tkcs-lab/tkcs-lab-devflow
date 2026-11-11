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

if (typeof module !== "undefined" && module.exports) {
  module.exports = { elapsed: elapsed, isHidden: isHidden, isSilent: isSilent, section: section, drift: drift };
}
