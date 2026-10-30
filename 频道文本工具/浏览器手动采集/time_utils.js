function inferPostTime(label, capturedAt, pageAgeSeconds = 0) {
  const raw = String(label || '').trim(), stamp = Date.parse(capturedAt);
  const empty = { created_at_estimated: null, created_at_earliest: null, created_at_latest: null, time_method: 'unknown', time_precision: 'unknown', time_label_raw: raw };
  if (!Number.isFinite(stamp)) return empty;
  const iso = ms => new Date(ms).toISOString();
  const exact = raw.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  if (exact) {
    const lower = Date.UTC(+exact[1], +exact[2]-1, +exact[3], +(exact[4]||0)-8, +(exact[5]||0), +(exact[6]||0));
    const width = exact[4] ? exact[6] ? 1000 : 60000 : 86400000;
    return { ...empty, created_at_estimated: iso(lower), created_at_earliest: iso(lower), created_at_latest: iso(lower+width), time_method:'displayed_calendar', time_precision:exact[4]?'minute_or_second':'day' };
  }
  if (raw === '刚刚') return { ...empty, created_at_estimated:iso(stamp),created_at_earliest:iso(stamp-60000-pageAgeSeconds*1000),created_at_latest:iso(stamp),time_method:'relative_estimate',time_precision:'about_one_minute' };
  const relative = raw.match(/(\d+)\s*(秒|分钟|小时|天|周)前/);
  if (relative) {
    const unit = {秒:1000,分钟:60000,小时:3600000,天:86400000,周:604800000}[relative[2]], n = +relative[1];
    return { ...empty, created_at_estimated:iso(stamp-n*unit), created_at_earliest:iso(stamp-(n+1)*unit-pageAgeSeconds*1000),created_at_latest:iso(stamp-Math.max(0,n-1)*unit),time_method:'relative_estimate',time_precision:relative[2]+'级估计，含页面驻留误差' };
  }
  const local = new Date(stamp+8*3600000), y = local.getUTCFullYear(), m=local.getUTCMonth(), d=local.getUTCDate();
  const calendar = raw.match(/^(今天|昨天|前天)(?:\s*(\d{1,2}):(\d{2}))?$/);
  if (calendar) {
    const offset={今天:0,昨天:1,前天:2}[calendar[1]], lower=Date.UTC(y,m,d-offset,+(calendar[2]||0)-8,+(calendar[3]||0));
    return {...empty,created_at_estimated:iso(lower),created_at_earliest:iso(lower),created_at_latest:iso(lower+(calendar[2]?60000:86400000)),time_method:'calendar_relative',time_precision:calendar[2]?'minute':'day'};
  }
  const short=raw.match(/^(\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$/);
  if(short){let year=y;let lower=Date.UTC(year,+short[1]-1,+short[2],+(short[3]||0)-8,+(short[4]||0));if(lower>stamp+86400000){year--;lower=Date.UTC(year,+short[1]-1,+short[2],+(short[3]||0)-8,+(short[4]||0));}return{...empty,created_at_estimated:iso(lower),created_at_earliest:iso(lower),created_at_latest:iso(lower+(short[3]?60000:86400000)),time_method:'year_inferred_from_capture',time_precision:short[3]?'minute':'day'};}
  return empty;
}
if (typeof globalThis !== 'undefined') globalThis.inferPostTime=inferPostTime;
if (typeof module !== 'undefined') module.exports={inferPostTime};
