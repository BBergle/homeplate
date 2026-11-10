// Live check of the Ask tab in a real headless Chrome, driven over the DevTools protocol (dev tool; Node 22+, no dependencies).
// usage: [OUT=/some/dir] [BASE=http://localhost:8000] [MEALIE=http://localhost:9925] node scripts/ask-check.mjs
// Needs the local stack running and the test admin to have an AI key saved. Asks real questions: costs a fraction of a cent.
// Signs in as the test Mealie's default admin. Adds one recipe through a card and deletes it again at the end.
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const OUT = (process.env.OUT || `${tmpdir()}/homeplate-ask-check`) + "/";
const BASE = process.env.BASE || "http://localhost:8000";
const MEALIE = process.env.MEALIE || "http://localhost:9925";
const USER = "changeme@example.com", PASS = "MyPassword"; // the test Mealie's stock admin, local only
const PORT = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
rmSync(OUT + "profile", { recursive: true, force: true });
mkdirSync(OUT + "shots", { recursive: true });

const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}profile`, "--no-first-run", "--hide-scrollbars", "about:blank",
], { stdio: "ignore" });

let page;
for (let i = 0; i < 40 && !page; i++) {
  await sleep(250);
  try { page = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let seq = 0; const pending = new Map();
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const cdp = (method, params = {}) => new Promise((res) => { const id = ++seq; pending.set(id, (m) => res(m.result ?? m)); ws.send(JSON.stringify({ id, method, params })); });
const js = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.value;
const go = async (path) => { await cdp("Page.navigate", { url: BASE + path }); await sleep(900); };
const shot = async (name) => { const r = await cdp("Page.captureScreenshot", { format: "png" }); writeFileSync(`${OUT}shots/${name}.png`, Buffer.from(r.data, "base64")); };
const size = (w) => cdp("Emulation.setDeviceMetricsOverride", { width: w, height: 844, deviceScaleFactor: 2, mobile: true });
const scheme = (v) => cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: v }] });
const until = async (expr, secs) => { for (let i = 0; i < secs * 4; i++) { if (await js(expr)) return true; await sleep(250); } return false; };
const out = [];
const check = (name, ok, extra = "") => out.push(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  | " + extra : ""}`);
const note = (text) => out.push("NOTE  " + text);

const token = (await (await fetch(`${MEALIE}/api/auth/token`, { method: "POST", body: new URLSearchParams({ username: USER, password: PASS }) })).json()).access_token;
const mealie = (path, init = {}) => fetch(MEALIE + path, { ...init, headers: { Authorization: `Bearer ${token}` } });
const named = async (name) => (await (await mealie(`/api/recipes?search=${encodeURIComponent(name)}`)).json()).items.filter((r) => r.name === name);
let added = null;

try {
  await cdp("Page.enable"); await size(390); await scheme("light");
  await go("/login");
  await js(`document.querySelector('[name=username]').value=${JSON.stringify(USER)}; document.querySelector('[name=password]').value=${JSON.stringify(PASS)}; document.querySelector('form').requestSubmit()`);
  await sleep(1500);
  check("sign in lands on Today", (await js("location.pathname")) === "/");

  await go("/ask");
  check("the test admin has an AI key saved", await js(`!!document.querySelector('.chat-form')`));
  if (await js(`!!document.querySelector('form[action="/ask/new"]')`)) { await js(`document.querySelector('form[action="/ask/new"]').requestSubmit()`); await sleep(1200); }
  await js(`window.__loaded = performance.timeOrigin`);
  const ask = async (q) => { await js(`document.querySelector('.chat-form textarea').value=${JSON.stringify(q)}; document.querySelector('.chat-form button').click()`); return Date.now(); };
  const answers = () => js(`document.querySelectorAll('.chat-ai:not(.chat-wait)').length`);

  // 1. a recipe search comes back as cards
  let t0 = await ask("Find me some arroz con pollo recipes");
  check("waiting bubble appears", await until(`!!document.querySelector('.chat-wait')`, 5));
  const done1 = await until(`!document.querySelector('.chat-wait') && document.querySelectorAll('.chat-ai').length === 1`, 150);
  check("answer arrives without a reload", done1 && (await js(`window.__loaded === performance.timeOrigin`)), `${((Date.now() - t0) / 1000).toFixed(1)}s`);
  const text1 = (await js(`document.querySelector('.chat-ai .chat-text')?.textContent`)) || "";
  check("answer is not an error", await js(`!document.querySelector('.chat-error')`), text1.slice(0, 120));
  check("no web address in the answer text", !/https?:\/\/|www\./.test(text1));
  const cards = await js(`[...document.querySelectorAll('.rcard')].map(c => ({ id: c.id, name: c.querySelector('.rcard-name').textContent, host: c.querySelector('.rcard-host').textContent, add: !!c.querySelector('form button'), note: c.querySelector('.rcard-note')?.textContent || '', photo: !!c.querySelector('img') }))`);
  check("at least two cards", (cards || []).length >= 2, (cards || []).map((c) => `${c.host}${c.add ? " [Add]" : " [" + c.note + "]"}${c.photo ? " +photo" : ""}`).join("; "));
  await sleep(1500);
  check("at least one card photo loaded", await js(`[...document.querySelectorAll('.rcard img')].some(i => i.complete && i.naturalWidth > 0)`));
  check("every card photo loaded", await js(`[...document.querySelectorAll('.rcard img')].every(i => i.complete && i.naturalWidth > 0)`));
  check("at least one Add button", (cards || []).some((c) => c.add));
  await shot("cards-390-light");

  // 2. Add imports once and links to the recipe
  const first = (cards || []).find((c) => c.add);
  if (first) {
    const before = (await named(first.name)).length;
    await js(`document.querySelector('#${first.id} form button').click()`);
    const ok = await until(`document.querySelector('#${first.id}')?.textContent.includes('Added to your recipes.')`, 90);
    check("card becomes Added without a reload", ok && (await js(`window.__loaded === performance.timeOrigin`)), await js(`document.querySelector('#${first.id} .rcard-note')?.textContent`));
    const href = await js(`document.querySelector('#${first.id} .rcard-note a')?.getAttribute('href')`);
    const r = await js(`fetch(${JSON.stringify(href || "/nope")}).then(async r => ({ status: r.status, text: await r.text() }))`);
    check("Open recipe shows the recipe in Homeplate", r?.status === 200 && r.text.includes(first.name.split(" ")[0]), `${href} -> ${r?.status}`);
    added = first.name;
    check("Mealie has one new recipe with that name", (await named(first.name)).length === before + 1, `before ${before}`);
    const again = await js(`fetch('/ask/cards/${first.id.replace("rcard-", "")}', { method: 'POST', headers: { 'HX-Request': 'true' } }).then(r => r.status)`);
    check("a second Add does not import again", (await named(first.name)).length === before + 1, `second POST answered ${again}`);
    check("another conversation's card id is refused", (await js(`fetch('/ask/cards/999999', { method: 'POST', headers: { 'HX-Request': 'true' } }).then(r => r.status)`)) === 404);
    await shot("cards-added-390-light");

    // 3. a question about saved recipes uses a look-up
    t0 = await ask("Which of my saved recipes use chicken? Name them.");
    const done3 = await until(`!document.querySelector('.chat-wait') && document.querySelectorAll('.chat-ai').length === 2`, 120);
    const text3 = (await js(`[...document.querySelectorAll('.chat-ai .chat-text')].pop()?.textContent`)) || "";
    check("saved-recipes question is answered", done3 && !(await js(`!!document.querySelector('.chat-ai:last-of-type.chat-error')`)), `${((Date.now() - t0) / 1000).toFixed(1)}s | ${text3.slice(0, 200).replace(/\n/g, " / ")}`);
    note(`answer ${text3.toLowerCase().includes(first.name.toLowerCase().split(" ").slice(0, 2).join(" ")) ? "names" : "does NOT name"} the recipe just added (${first.name})`);
  }

  // 4. layout with cards on screen
  for (const w of [375, 390, 430]) for (const mode of ["light", "dark"]) {
    await size(w); await scheme(mode); await go("/ask"); await sleep(600);
    const m = await js(`(() => { const n = document.querySelector('nav.tabs').getBoundingClientRect(); window.scrollTo(0, document.documentElement.scrollHeight); const f = document.querySelector('form[action="/ask/new"] button').getBoundingClientRect(); const wide = [...document.querySelectorAll('.rcard, .rcard *')].filter(e => e.getBoundingClientRect().right > innerWidth + 0.5).length; return { overflow: document.documentElement.scrollWidth - innerWidth, gap: Math.round(n.top - f.bottom), wide }; })()`);
    check(`layout ${w} ${mode}`, m.overflow <= 0 && m.gap >= 0 && m.wide === 0, `sideways overflow ${m.overflow}px, card parts past the edge ${m.wide}, last button to tab bar ${m.gap}px`);
    await js(`document.querySelector('.rcard')?.scrollIntoView({ block: 'start' })`); await sleep(400);
    await shot(`cards-${w}-${mode}`);
  }
} catch (e) { out.push("SCRIPT ERROR " + (e.stack || e)); }

if (added) for (const r of await named(added)) { const d = await mealie(`/api/recipes/${r.slug}`, { method: "DELETE" }); note(`cleanup: deleted ${r.slug} from the test Mealie (${d.status})`); }
console.log(out.join("\n"));
console.log(`screenshots in ${OUT}shots`);
ws.close(); chrome.kill();
process.exit(out.some((l) => l.startsWith("FAIL") || l.startsWith("SCRIPT ERROR")) ? 1 : 0);
