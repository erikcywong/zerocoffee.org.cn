/* ZeroCarbon Verify — English / 中文
 *
 * The site is authored in English. This layer swaps the rendered strings for
 * Chinese using a dictionary keyed on the exact English text, so there is no
 * second copy of the HTML to drift. A language change reloads the page: that
 * is simpler and far less bug-prone than trying to restore every text node.
 */
(function () {
  'use strict';

  var KEY = 'zv-lang';
  var LANG = localStorage.getItem(KEY) === 'zh' ? 'zh' : 'en';
  // ?lang=zh makes the state linkable and testable
  var qs = new URLSearchParams(location.search).get('lang');
  if (qs === 'zh' || qs === 'en') { LANG = qs; localStorage.setItem(KEY, qs); }
  var SKIP = /^(SCRIPT|STYLE|CODE|PRE|KBD|TEXTAREA|SVG|PATH)$/;
  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  var dict = null;
  // resolve the dictionary against the script's own URL, not the page URL:
  // on /registry/ a bare 'assets/i18n.json' would point at /registry/assets/...
  var SELF = document.currentScript ? document.currentScript.src : '';
  var ROOT = SELF.slice(0, SELF.lastIndexOf('assets/i18n.js')) || '/';

  function norm(s) { return String(s).replace(/\s+/g, ' ').trim(); }

  function translateTree(node) {
    if (node.nodeType === 3) {
      var raw = node.nodeValue;
      var key = norm(raw);
      if (!key || key.length < 2 || !dict[key]) return;
      var lead = raw.match(/^\s*/)[0];
      var trail = raw.match(/\s*$/)[0];
      node.nodeValue = lead + dict[key] + trail;
      return;
    }
    if (node.nodeType !== 1) return;
    if (SKIP.test(node.tagName)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i];
      if (node.hasAttribute && node.hasAttribute(a)) {
        var v = node.getAttribute(a);
        var k = norm(v);
        if (dict[k]) node.setAttribute(a, dict[k]);
      }
    }
    for (var c = node.firstChild; c; c = c.nextSibling) translateTree(c);
  }

  function syncFilm() {
    var src = document.getElementById('homeFilmSrc');
    if (!src) return;
    var video = document.getElementById('homeFilm');
    var cap = document.getElementById('homeFilmCap');
    var file = ROOT + 'assets/video/home-' + LANG + '.mp4';
    if (src.src.indexOf(file) === -1) {
      var t = video ? video.currentTime : 0;
      src.src = file;
      if (video) { video.poster = ROOT + 'assets/video/home-' + LANG + '.jpg'; video.load(); video.currentTime = t; }
    }
    if (cap) {
      var d = dict[norm(cap.innerHTML.replace(/<[^>]+>/g, ''))];
      if (d) cap.innerHTML = d;
    }
    var sw = document.getElementById('filmSwitch');
    if (sw) {
      Array.prototype.forEach.call(sw.querySelectorAll('button'), function (b) {
        b.classList.toggle('on', b.dataset.lang === LANG);
      });
    }
  }

  function renderSwitch() {
    var host = document.querySelector('.util .right');
    if (!host || document.getElementById('langSwitch')) return;
    var wrap = document.createElement('span');
    wrap.className = 'lang-switch';
    wrap.id = 'langSwitch';
    wrap.innerHTML =
      '<button data-lang="en" class="' + (LANG === 'en' ? 'on' : '') + '">EN</button>' +
      '<button data-lang="zh" class="' + (LANG === 'zh' ? 'on' : '') + '">中文</button>';
    host.insertBefore(wrap, host.firstChild);
    wrap.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b || b.dataset.lang === LANG) return;
      localStorage.setItem(KEY, b.dataset.lang);
      location.reload();
    });
  }

  function boot() {
    document.documentElement.lang = LANG === 'zh' ? 'zh-CN' : 'en';
    renderSwitch();
    // the film's own switch must follow the site language, not fight it
    var filmSwitch = document.getElementById('filmSwitch');
    if (filmSwitch) {
      filmSwitch.addEventListener('click', function (e) {
        var b = e.target.closest('button');
        if (!b) return;
        localStorage.setItem(KEY, b.dataset.lang);
      }, true);
    }
    if (LANG !== 'zh') return;
    fetch(ROOT + 'assets/i18n.json')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        dict = d;
        var t = document.title;
        if (d[norm(t)]) document.title = d[norm(t)];
        translateTree(document.body);
        syncFilm();
      })
      .catch(function () { /* stay in English rather than half-translate */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
