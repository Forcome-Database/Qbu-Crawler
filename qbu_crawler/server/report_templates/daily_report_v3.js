/**
 * Qbu-Crawler Daily Report V3.1 — Refined Editorial UI
 * Vanilla JS. Chart.js loaded separately via CDN.
 * Features: animated tabs, CSS gauge, counter-up, collapsible cards,
 *   lightbox, table sort/filter/pagination, sticky KPI, Chart.js init.
 */
(function () {
  'use strict';

  var PAGE_SIZE = 20;

  /* =========================================================================
     1. TAB NAVIGATION — pill style, fade-slide animation
     ========================================================================= */

  function initTabs() {
    var btns = document.querySelectorAll('.tab-nav .tab-btn[data-tab]');
    var panels = document.querySelectorAll('.tab-panel');

    function activate(tabId) {
      btns.forEach(function (b) { b.classList.toggle('tab-active', b.getAttribute('data-tab') === tabId); });
      panels.forEach(function (p) {
        var isTarget = p.id === 'tab-' + tabId;
        if (isTarget && !p.classList.contains('tab-active')) {
          p.classList.add('tab-active');
          // Re-trigger reveal animations inside this panel
          p.querySelectorAll('.reveal').forEach(function (el) {
            el.classList.remove('revealed');
            void el.offsetWidth;
            el.classList.add('revealed');
          });
        } else if (!isTarget) {
          p.classList.remove('tab-active');
        }
      });
    }

    btns.forEach(function (btn) {
      btn.addEventListener('click', function () { activate(btn.getAttribute('data-tab')); });
    });

    // Keyboard: arrow left/right to switch tabs
    document.querySelector('.tab-nav').addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      var active = document.querySelector('.tab-btn.tab-active');
      var arr = Array.prototype.slice.call(btns);
      var idx = arr.indexOf(active);
      if (idx < 0) return;
      var next = e.key === 'ArrowRight' ? idx + 1 : idx - 1;
      if (next >= 0 && next < arr.length) {
        arr[next].focus();
        activate(arr[next].getAttribute('data-tab'));
      }
    });

    // Default: show first tab
    if (btns.length > 0) activate(btns[0].getAttribute('data-tab'));
  }

  /* =========================================================================
     2. CSS-ONLY GAUGE INIT
     ========================================================================= */

  function initGauge() {
    var wrapper = document.querySelector('.gauge-wrapper');
    if (!wrapper) return;

    var val = parseFloat(wrapper.getAttribute('data-health') || '50');
    var pct = Math.max(0, Math.min(1, val / 100));

    // Determine gauge color
    var color;
    if (val >= 60)      color = '#047857'; // low / green
    else if (val >= 45) color = '#a16207'; // medium / amber
    else                color = '#b91c1c'; // critical / red

    var fill = wrapper.querySelector('.gauge-fill');
    if (fill) {
      fill.style.setProperty('--gauge-pct', pct);
      fill.style.setProperty('--gauge-color', color);
    }

    // Animate number counter-up
    var numEl = wrapper.querySelector('.gauge-value');
    if (numEl) animateCounter(numEl, 0, val, 1200, 1);
  }

  /* =========================================================================
     F011 §4.2.5 — Render the single health-trend primary chart as inline SVG.
     Reads data-series-own / data-series-competitor JSON from the container.
     Vanilla DOM, no external deps. No-ops if container missing or both series
     empty (bootstrap branch renders a notice instead of this container).
     ========================================================================= */
  function initHealthTrendChart() {
    var container = document.getElementById('health-trend-chart');
    if (!container) return;
    var seriesOwn, seriesCompetitor;
    try {
      seriesOwn = JSON.parse(container.getAttribute('data-series-own') || '[]');
      seriesCompetitor = JSON.parse(container.getAttribute('data-series-competitor') || '[]');
    } catch (e) { return; }
    var allPoints = (seriesOwn || []).concat(seriesCompetitor || []);
    if (!allPoints.length) return;

    var w = container.clientWidth || 600;
    var h = 280;
    var padL = 40, padR = 16, padT = 16, padB = 32;
    var innerW = w - padL - padR, innerH = h - padT - padB;

    var dates = allPoints.map(function (p) { return p.date; });
    var uniqDates = [];
    dates.forEach(function (d) { if (uniqDates.indexOf(d) < 0) uniqDates.push(d); });
    uniqDates.sort();
    var values = allPoints.map(function (p) { return p.value; }).filter(function (v) { return typeof v === 'number'; });
    var vMin = Math.min.apply(null, values.concat([0]));
    var vMax = Math.max.apply(null, values.concat([100]));
    if (vMax === vMin) vMax = vMin + 1;

    function xFor(date) {
      var idx = uniqDates.indexOf(date);
      if (uniqDates.length <= 1) return padL + innerW / 2;
      return padL + (idx / (uniqDates.length - 1)) * innerW;
    }
    function yFor(value) {
      return padT + innerH - ((value - vMin) / (vMax - vMin)) * innerH;
    }
    function pathFor(series, color) {
      if (!series || !series.length) return '';
      var d = series.map(function (p, i) {
        return (i === 0 ? 'M' : 'L') + xFor(p.date).toFixed(1) + ',' + yFor(p.value).toFixed(1);
      }).join(' ');
      return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2"/>';
    }
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="100%" height="' + h + '">';
    // Axes
    svg += '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (padT + innerH) + '" stroke="#cbd5e1"/>';
    svg += '<line x1="' + padL + '" y1="' + (padT + innerH) + '" x2="' + (padL + innerW) + '" y2="' + (padT + innerH) + '" stroke="#cbd5e1"/>';
    svg += pathFor(seriesOwn, '#16a34a');         // green: own
    svg += pathFor(seriesCompetitor, '#dc2626');  // red: competitor
    // Legend
    svg += '<g font-size="11" font-family="sans-serif">';
    svg += '<rect x="' + (padL + 4) + '" y="' + (padT + 4) + '" width="10" height="2" fill="#16a34a"/>';
    svg += '<text x="' + (padL + 18) + '" y="' + (padT + 8) + '">自有</text>';
    svg += '<rect x="' + (padL + 60) + '" y="' + (padT + 4) + '" width="10" height="2" fill="#dc2626"/>';
    svg += '<text x="' + (padL + 74) + '" y="' + (padT + 8) + '">竞品</text>';
    svg += '</g>';
    svg += '</svg>';
    container.innerHTML = svg;
  }

  // F011 §4.2.5 / Task 3.3 — initTrendPanels (and the .trend-panel print-mode loop
  // below) only fire when daily_report_v3_legacy.html.j2 renders the multi-panel
  // view/dimension switcher. The current daily_report_v3.html.j2 emits a single
  // primary chart + 3 drill-downs and does NOT use these classes, so the selectors
  // below find nothing and the function early-returns. KEEP this code until Task 4.6
  // retires the legacy template.
  function initTrendPanels() {
    var viewBtns = document.querySelectorAll('.trend-view-btn[data-trend-view]');
    var dimensionBtns = document.querySelectorAll('.trend-subtab-btn[data-trend-dimension]');
    var panels = document.querySelectorAll('.trend-panel[data-trend-view][data-trend-dimension]');
    if (!viewBtns.length || !dimensionBtns.length || !panels.length) return;

    var activeViewBtn = document.querySelector('.trend-view-btn.trend-active') || viewBtns[0];
    var activeDimensionBtn = document.querySelector('.trend-subtab-btn.trend-active') || dimensionBtns[0];
    var currentView = activeViewBtn.getAttribute('data-trend-view');
    var currentDimension = activeDimensionBtn.getAttribute('data-trend-dimension');

    function renderTrendPanel() {
      viewBtns.forEach(function (btn) {
        btn.classList.toggle('trend-active', btn.getAttribute('data-trend-view') === currentView);
      });
      dimensionBtns.forEach(function (btn) {
        btn.classList.toggle('trend-active', btn.getAttribute('data-trend-dimension') === currentDimension);
      });
      panels.forEach(function (panel) {
        var matchesView = panel.getAttribute('data-trend-view') === currentView;
        var matchesDimension = panel.getAttribute('data-trend-dimension') === currentDimension;
        panel.classList.toggle('trend-panel-active', matchesView && matchesDimension);
      });
      // 修 9: toggle data-driven view-note banners by active view
      document.querySelectorAll('[data-trend-view-note]').forEach(function (el) {
        el.hidden = el.getAttribute('data-trend-view-note') !== currentView;
      });
    }

    viewBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        currentView = btn.getAttribute('data-trend-view');
        renderTrendPanel();
      });
    });

    dimensionBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        currentDimension = btn.getAttribute('data-trend-dimension');
        renderTrendPanel();
      });
    });

    renderTrendPanel();
  }

  /* =========================================================================
     3. COUNTER-UP ANIMATION
     ========================================================================= */

  function animateCounter(el, from, to, duration, decimals) {
    var start = performance.now();
    function step(now) {
      var pct = Math.min((now - start) / duration, 1);
      // Ease-out cubic
      var eased = 1 - Math.pow(1 - pct, 3);
      var current = from + (to - from) * eased;
      el.textContent = current.toFixed(decimals || 0);
      if (pct < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function initCounters() {
    document.querySelectorAll('.kpi-value[data-count]').forEach(function (el) {
      var raw = el.getAttribute('data-count');
      var target = parseFloat(raw);
      if (isNaN(target)) return;
      var decimals = raw.indexOf('.') >= 0 ? (raw.split('.')[1] || '').length : 0;
      var suffix = el.getAttribute('data-suffix') || '';
      var origText = el.textContent;
      el.textContent = '0' + suffix;

      // Use IntersectionObserver for scroll-triggered animation
      if ('IntersectionObserver' in window) {
        var obs = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              animateCounter(el, 0, target, 800, decimals);
              if (suffix) {
                var id = setInterval(function () {
                  if (!el._counting) { el.textContent = el.textContent + suffix; clearInterval(id); }
                }, 850);
              }
              obs.disconnect();
            }
          });
        }, { threshold: 0.3 });
        obs.observe(el);
      } else {
        el.textContent = origText;
      }
    });
  }

  /* =========================================================================
     4. COLLAPSIBLE CARDS — smooth animation
     ========================================================================= */

  function initCollapsible() {
    document.querySelectorAll('.issue-card').forEach(function (card) {
      var header = card.querySelector('.card-header');
      if (!header) return;

      if (card.getAttribute('data-default-collapsed') === 'true') {
        card.classList.add('card-collapsed');
      }

      header.addEventListener('click', function () {
        card.classList.toggle('card-collapsed');
      });
    });
  }

  /* =========================================================================
     5. LIGHTBOX — keyboard + backdrop close
     ========================================================================= */

  function initLightbox() {
    var lightbox = document.getElementById('lightbox');
    var lbImg = document.getElementById('lightbox-img');
    var closeBtn = document.getElementById('lightbox-close');
    if (!lightbox || !lbImg) return;

    function openLB(src, alt) {
      lbImg.src = src;
      lbImg.alt = alt || '';
      lightbox.classList.add('lightbox-open');
      document.body.style.overflow = 'hidden';
    }

    function closeLB() {
      lightbox.classList.remove('lightbox-open');
      lbImg.src = '';
      document.body.style.overflow = '';
    }

    document.addEventListener('click', function (e) {
      if (e.target.classList.contains('evidence-img')) {
        openLB(e.target.getAttribute('data-full') || e.target.src, e.target.alt);
      }
    });

    if (closeBtn) closeBtn.addEventListener('click', closeLB);
    lightbox.addEventListener('click', function (e) { if (e.target === lightbox || e.target.classList.contains('lightbox-backdrop')) closeLB(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && lightbox.classList.contains('lightbox-open')) closeLB(); });
  }

  /* =========================================================================
     6. TABLE SORT
     ========================================================================= */

  function initTableSort() {
    document.querySelectorAll('.data-table').forEach(function (table) {
      var headers = table.querySelectorAll('th[data-sortable]');

      headers.forEach(function (th) {
        if (!th.querySelector('.sort-indicator')) {
          var s = document.createElement('span');
          s.className = 'sort-indicator';
          s.textContent = '⇅';
          th.appendChild(s);
        }

        th.addEventListener('click', function () {
          var asc = th.classList.contains('sort-asc');
          var idx = Array.prototype.indexOf.call(th.parentNode.children, th);

          headers.forEach(function (h) {
            h.classList.remove('sort-asc', 'sort-desc');
            var ind = h.querySelector('.sort-indicator');
            if (ind) ind.textContent = '⇅';
          });

          var nextAsc = !asc;
          th.classList.add(nextAsc ? 'sort-asc' : 'sort-desc');
          var indicator = th.querySelector('.sort-indicator');
          if (indicator) indicator.textContent = nextAsc ? '▲' : '▼';

          var tbody = table.querySelector('tbody');
          if (!tbody) return;
          var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

          rows.sort(function (a, b) {
            var ca = (a.cells[idx] ? a.cells[idx].textContent.trim() : '');
            var cb = (b.cells[idx] ? b.cells[idx].textContent.trim() : '');
            var na = parseFloat(ca.replace(/[^0-9.\-]/g, ''));
            var nb = parseFloat(cb.replace(/[^0-9.\-]/g, ''));
            var isNum = !isNaN(na) && !isNaN(nb);
            var cmp = isNum ? (na - nb) : ca.localeCompare(cb, 'zh-CN');
            return nextAsc ? cmp : -cmp;
          });

          rows.forEach(function (r) { tbody.appendChild(r); });

          // Re-apply pagination after sort
          if (table.id === 'review-table') applyReviewPagination();
        });
      });
    });
  }

  /* =========================================================================
     7. TABLE FILTER + OWNERSHIP PILLS + PAGINATION
     ========================================================================= */

  var currentPage = 1;
  var currentFilter = '';
  var currentOwnership = 'all';

  function getFilteredRows() {
    var table = document.getElementById('review-table');
    if (!table) return [];
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));

    return rows.filter(function (row) {
      var text = row.textContent.toLowerCase();
      var matchText = !currentFilter || text.indexOf(currentFilter) !== -1;

      var matchOwnership = true;
      if (currentOwnership !== 'all') {
        var ownerCell = row.cells[1];
        if (ownerCell) {
          var val = ownerCell.textContent.trim();
          matchOwnership = (currentOwnership === 'own' && val === '自有') ||
                           (currentOwnership === 'comp' && val === '竞品');
        }
      }

      return matchText && matchOwnership;
    });
  }

  function applyReviewPagination() {
    var filtered = getFilteredRows();
    var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    // Hide all, show current page
    var table = document.getElementById('review-table');
    if (!table) return;
    var allRows = table.querySelectorAll('tbody tr');
    allRows.forEach(function (r) { r.style.display = 'none'; });

    var start = (currentPage - 1) * PAGE_SIZE;
    var end = start + PAGE_SIZE;
    filtered.forEach(function (r, i) {
      r.style.display = (i >= start && i < end) ? '' : 'none';
    });

    // Update count
    var countEl = document.querySelector('.filter-count');
    if (countEl) {
      countEl.textContent = filtered.length + ' 条' + (filtered.length !== allRows.length ? ' / ' + allRows.length + ' 总计' : '');
    }

    // Render pagination
    renderPagination(totalPages, filtered.length);
  }

  function renderPagination(totalPages, totalItems) {
    var container = document.getElementById('review-pagination');
    if (!container) return;
    container.innerHTML = '';

    if (totalPages <= 1) return;

    // Prev
    var prev = document.createElement('button');
    prev.textContent = '‹';
    prev.disabled = currentPage <= 1;
    prev.addEventListener('click', function () { currentPage--; applyReviewPagination(); });
    container.appendChild(prev);

    // Page numbers (show max 7 with ellipsis)
    var pages = [];
    if (totalPages <= 7) {
      for (var i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages = [1];
      if (currentPage > 3) pages.push('...');
      for (var j = Math.max(2, currentPage - 1); j <= Math.min(totalPages - 1, currentPage + 1); j++) pages.push(j);
      if (currentPage < totalPages - 2) pages.push('...');
      pages.push(totalPages);
    }

    pages.forEach(function (p) {
      if (p === '...') {
        var sp = document.createElement('span');
        sp.className = 'pagination-info';
        sp.textContent = '…';
        container.appendChild(sp);
      } else {
        var btn = document.createElement('button');
        btn.textContent = p;
        if (p === currentPage) btn.classList.add('active');
        btn.addEventListener('click', function () { currentPage = p; applyReviewPagination(); });
        container.appendChild(btn);
      }
    });

    // Next
    var next = document.createElement('button');
    next.textContent = '›';
    next.disabled = currentPage >= totalPages;
    next.addEventListener('click', function () { currentPage++; applyReviewPagination(); });
    container.appendChild(next);
  }

  function initTableFilter() {
    var input = document.querySelector('.filter-input[data-target="review-table"]');
    if (!input) return;

    input.addEventListener('input', function () {
      currentFilter = input.value.toLowerCase().trim();
      currentPage = 1;
      applyReviewPagination();
    });

    // Ownership filter pills
    document.querySelectorAll('.filter-pill[data-ownership]').forEach(function (pill) {
      pill.addEventListener('click', function () {
        document.querySelectorAll('.filter-pill[data-ownership]').forEach(function (p) { p.classList.remove('active'); });
        pill.classList.add('active');
        currentOwnership = pill.getAttribute('data-ownership');
        currentPage = 1;
        applyReviewPagination();
      });
    });

    // Initial pagination
    applyReviewPagination();
  }

  /* =========================================================================
     8. STICKY KPI SHADOW
     ========================================================================= */

  function initStickyKpi() {
    var bar = document.querySelector('.kpi-bar');
    if (!bar) return;
    function onScroll() { bar.classList.toggle('scrolled', window.scrollY > 10); }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* =========================================================================
     9. PRINT BUTTON
     ========================================================================= */

  function initPrint() {
    var btn = document.getElementById('btn-print');
    if (!btn) return;

    btn.addEventListener('click', function () {
      preparePrintAssets();
      setTimeout(function () { window.print(); }, 200);
    });

    // beforeprint: just ensure assets are ready (no window.print call)
    window.addEventListener('beforeprint', preparePrintAssets);
  }

  function preparePrintAssets() {
    // 1. Force-load all lazy images
    document.querySelectorAll('img[loading="lazy"]').forEach(function (img) {
      img.removeAttribute('loading');
      if (!img.complete && img.src) { img.src = img.src; }
    });

    // 2. Show all review table rows (remove pagination for print)
    var table = document.getElementById('review-table');
    if (table) {
      table.querySelectorAll('tbody tr').forEach(function (row) {
        row.style.display = '';
      });
    }

    document.querySelectorAll('.trend-panel').forEach(function (panel) {
      panel.classList.add('trend-panel-active');
    });
  }

  /* =========================================================================
     10. CHART.JS INIT — with theme color override
     ========================================================================= */

  function initCharts() {
    if (typeof Chart === 'undefined') return;

    // Override default chart colors to match our theme
    Chart.defaults.font.family = "'DM Sans', 'Noto Sans SC', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#555770';
    Chart.defaults.borderColor = '#e5e4e0';

    document.querySelectorAll('canvas[data-chart-config]').forEach(function (canvas) {
      var raw = canvas.getAttribute('data-chart-config');
      if (!raw) return;

      var config;
      try { config = JSON.parse(raw); } catch (e) { return; }

      if (!config.options) config.options = {};
      config.options.responsive = true;
      if (config.options.maintainAspectRatio === undefined) config.options.maintainAspectRatio = true;
      if (!config.options.plugins) config.options.plugins = {};
      if (!config.options.plugins.legend) config.options.plugins.legend = { position: 'bottom', labels: { padding: 16, usePointStyle: true } };
      if (!config.options.plugins.tooltip) config.options.plugins.tooltip = { mode: 'index', intersect: false };

      // Theme colors: replace old palette with new
      if (config.data && config.data.datasets) {
        config.data.datasets.forEach(function (ds) {
          if (ds.backgroundColor === '#93543f') ds.backgroundColor = '#4f46e5';
          if (ds.borderColor === '#93543f') ds.borderColor = '#4f46e5';
          if (ds.backgroundColor === '#345f57') ds.backgroundColor = '#047857';
          if (ds.borderColor === '#345f57') ds.borderColor = '#047857';
          // Radar fill
          if (ds.backgroundColor === 'rgba(147, 84, 63, 0.15)') ds.backgroundColor = 'rgba(79, 70, 229, 0.12)';
          if (ds.backgroundColor === 'rgba(52, 95, 87, 0.15)') ds.backgroundColor = 'rgba(4, 120, 87, 0.12)';
          // Bar chart colors
          if (Array.isArray(ds.backgroundColor)) {
            ds.backgroundColor = ds.backgroundColor.map(function (c) {
              if (c === '#345f57') return '#047857';
              if (c === '#b0823a') return '#a16207';
              if (c === '#93543f') return '#b91c1c';
              return c;
            });
          }
        });
      }

      try { new Chart(canvas, config); } catch (e) { /* graceful skip */ }
    });
  }

  /* =========================================================================
     11. SCROLL-TRIGGERED REVEAL
     ========================================================================= */

  function initReveal() {
    var els = document.querySelectorAll('.reveal');
    if (!els.length) return;

    if ('IntersectionObserver' in window) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            obs.unobserve(entry.target);
          }
        });
      }, { threshold: 0.1 });
      els.forEach(function (el) { obs.observe(el); });
    } else {
      els.forEach(function (el) { el.classList.add('revealed'); });
    }
  }

  /* =========================================================================
     12. STAR RATING HELPER
     ========================================================================= */

  function initStarRatings() {
    document.querySelectorAll('[data-rating]').forEach(function (el) {
      var rating = parseFloat(el.getAttribute('data-rating'));
      if (isNaN(rating)) return;
      var stars = '';
      for (var i = 1; i <= 5; i++) {
        stars += i <= rating ? '★' : '☆';
      }
      el.textContent = stars;
    });
  }

  /* =========================================================================
     F011 §4.2.6 — Panorama client-side filters (5 filters: ownership,
     rating, has_images, recent, label). Reads tr.dataset, hides non-matches.
     ========================================================================= */

  function matchPanoramaFilters(d, f) {
    if (f.ownership && d.ownership !== f.ownership) return false;
    var rating = parseFloat(d.rating);
    if (f.rating === 'low' && !(rating <= 2)) return false;
    if (f.rating === 'mid' && rating !== 3) return false;
    if (f.rating === 'high' && !(rating >= 4)) return false;
    if (f.has_images && d.hasImages !== '1') return false;
    if (f.recent && d.recent !== '1') return false;
    if (f.label && (d.labels || '').split(',').indexOf(f.label) === -1) return false;
    return true;
  }

  function applyPanoramaFilters() {
    var ownEl = document.querySelector('.panorama-filters [name=ownership]');
    var rateEl = document.querySelector('.panorama-filters [name=rating]');
    var imgEl = document.querySelector('.panorama-filters [name=has_images]');
    var recEl = document.querySelector('.panorama-filters [name=recent]');
    var labEl = document.querySelector('.panorama-filters [name=label]');
    var filters = {
      ownership: ownEl ? ownEl.value : '',
      rating: rateEl ? rateEl.value : '',
      has_images: imgEl ? imgEl.checked : false,
      recent: recEl ? recEl.checked : false,
      label: labEl ? labEl.value : '',
    };
    document.querySelectorAll('.panorama-table tbody tr').forEach(function (tr) {
      tr.style.display = matchPanoramaFilters(tr.dataset, filters) ? '' : 'none';
    });
  }

  function initPanoramaFilters() {
    var inputs = document.querySelectorAll('.panorama-filters select, .panorama-filters input');
    if (!inputs.length) return;
    inputs.forEach(function (el) {
      el.addEventListener('change', applyPanoramaFilters);
    });
  }

  /* =========================================================================
     BOOT
     ========================================================================= */

  function boot() {
    initTabs();
    initTrendPanels();
    initHealthTrendChart();
    initGauge();
    initCounters();
    initCollapsible();
    initLightbox();
    initTableSort();
    initTableFilter();
    initStickyKpi();
    initPrint();
    initCharts();
    initReveal();
    initStarRatings();
    initPanoramaFilters();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
