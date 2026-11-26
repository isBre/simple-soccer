// The Game (web/game.js has the overview): #/game/sounds, every sound and song of the game on its own button, to listen to
// them and tune web/sound.js and web/music.js. Not linked from the menu.
import { G, btn, card, esc, go, mount, shell } from "./core.js";

const GROUPS = [
  ["The ball", [["kick-pass", "Pass"], ["kick-mid", "Firm pass"], ["kick-shot", "Shot"], ["post", "Post"], ["wall", "Boards"], ["net", "Net"], ["body", "Off a player"], ["tackle", "Players collide"]]],
  ["The referee", [["wh-kickoff", "Kickoff"], ["wh-overtime", "Overtime"], ["wh-fulltime", "Full time"]]],
  ["The crowd", [["crowd", "Crowd on / off"], ["ooh", "Ooh (near miss)"], ["applause", "Applause"], ["fans", "Fans whistle"], ["roar", "Roar"],
    ["goal-mine", "Your goal"], ["goal-theirs", "Their goal"], ["fulltime", "Full-time cheer"]]],
  ["Menus", [["ui-move", "Move"], ["ui-select", "Select"], ["ui-back", "Back"], ["ui-toggle", "Toggle"]]],
];
const ACT = {
  "kick-pass": () => Sound.kick(0.35), "kick-mid": () => Sound.kick(0.65), "kick-shot": () => Sound.kick(1),
  post: () => Sound.bounce("post", 0.9), wall: () => Sound.bounce("wall", 0.8), net: () => Sound.bounce("net", 0.8), body: () => Sound.bounce("body", 0.7),
  tackle: () => Sound.tackle(0.8),
  "wh-kickoff": () => Sound.whistle(Sound.WHISTLE.kickoff), "wh-overtime": () => Sound.whistle(Sound.WHISTLE.overtime), "wh-fulltime": () => Sound.whistle(Sound.WHISTLE.fulltime),
  ooh: () => Sound.ooh(1), applause: () => Sound.applause(3, 0.7), fans: () => Sound.fans(3), roar: () => Sound.roar(1),
  "goal-mine": () => Sound.goal(true), "goal-theirs": () => Sound.goal(false), fulltime: () => Sound.fulltime(),
  "ui-move": () => Sound.ui("move"), "ui-select": () => Sound.ui("select"), "ui-back": () => Sound.ui("back"), "ui-toggle": () => Sound.ui("toggle"),
};

export function soundsPage() {
  const row = (items) => `<div class="snd-row">${items.map(([k, label]) => btn(esc(label), `type="button" data-s="${k}"`)).join("")}</div>`;
  const songs = Music.songs.map((n, i) => btn(esc(n), `type="button" data-song="${i}"`)).join("");
  const v = mount(shell(`<div class="snd-page">
    <h1 class="g-h1">Sounds</h1>
    <p class="g-sub">Every sound of the game on its own. All of it is synthesised in the browser (web/sound.js, web/music.js).</p>
    ${GROUPS.map(([title, items]) => card(row(items) + (title === "The crowd"
      ? `<label class="snd-hype">Excitement <input type="range" id="snd-hype" min="0" max="100" value="0"> <span>(the ball near a goal)</span></label>` : ""), title)).join("")}
    ${card(`<div class="snd-row">${songs}${btn("Next song", 'type="button" data-song="next"')}${btn("Stop", 'type="button" data-song="stop"', "ghost")}</div>
      <p class="snd-now">Playing: <b id="snd-now">nothing</b> <span id="snd-off"></span></p>`, "Menu music")}
  </div>`, [["Esc", "menu"]]));
  let crowd = false;
  v.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => Sound.unlock().then(() => {
    if (b.dataset.s === "crowd") { crowd = !crowd; if (crowd) Sound.crowdOn(); else Sound.crowdOff(); b.classList.toggle("on", crowd); return; }
    ACT[b.dataset.s]();
  })));
  v.querySelector("#snd-hype").oninput = (e) => Sound.hype(e.target.value / 100);
  v.querySelectorAll("[data-song]").forEach((b) => (b.onclick = () => Sound.unlock().then(() => {
    const k = b.dataset.song;
    if (k === "stop") Music.stop(0.5); else if (k === "next") Music.next(); else Music.song(Number(k));
  })));
  const now = v.querySelector("#snd-now"), off = v.querySelector("#snd-off");
  const tick = setInterval(() => {
    if (!now.isConnected) { clearInterval(tick); return; }
    now.textContent = Music.playing || "nothing";
    off.textContent = !Sound.on ? "(all sound is off: N)" : !Sound.musicOn ? "(music is off: M)" : Sound.state !== "running" ? "(click anything to start the audio)" : "";
  }, 250);
  G.keyHandler = (e, down) => { if (down && e.key === "Escape") go("#/game"); };
}
