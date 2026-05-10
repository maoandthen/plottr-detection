/* plottr — search dropdown
 * Vanilla JS autocomplete. No framework dependency.
 *
 * Initialise once on page load:
 *   plottr.initSearch({ inputSelector: '#plottr-search', endpoint: '/api/search/autocomplete' });
 */

(function (window) {
  'use strict';

  const PLOTTR = window.plottr || (window.plottr = {});

  PLOTTR.initSearch = function (options) {
    const opts = Object.assign({
      inputSelector: '#plottr-search',
      dropdownSelector: '#plottr-search-dropdown',
      endpoint: '/api/search/autocomplete',
      resultsPath: '/search',
      minQueryLength: 2,
      debounceMs: 180,
    }, options || {});

    const input = document.querySelector(opts.inputSelector);
    const dropdown = document.querySelector(opts.dropdownSelector);
    const clearBtn = document.querySelector('.search-input-wrap .clear-btn');
    
    if (!input || !dropdown) {
      console.warn('plottr.initSearch: input or dropdown not found');
      return;
    }

    let debounceTimer = null;
    let lastQuery = '';
    let activeIndex = -1;
    let allItems = [];
    let inflightController = null;

    function highlight(text, query) {
      if (!query || !text) return escapeHtml(text || '');
      const escaped = escapeHtml(text);
      const re = new RegExp('(' + escapeRegex(query) + ')', 'gi');
      return escaped.replace(re, '<em>$1</em>');
    }

    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }

    function escapeRegex(s) {
      return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function formatNumber(n) {
      if (n === null || n === undefined) return '0';
      return n.toLocaleString('en-GB');
    }

    function renderItem(group, item, query) {
      const a = document.createElement('a');
      a.className = 'item';
      a.href = item.url;
      a.dataset.index = allItems.length;
      allItems.push(a);

      let leftHtml = '';
      let rightHtml = '';

      if (group.type === 'company') {
        leftHtml = `
          <div>
            <div class="name">${highlight(item.name, query)}</div>
            <div class="meta">CH ${item.id}${item.status ? ' · ' + escapeHtml(item.status) : ''}</div>
          </div>`;
        rightHtml = `
          <div>
            <div class="stat">${formatNumber(item.title_count)}</div>
            <div class="stat-label">${item.title_count === 1 ? 'title' : 'titles'}</div>
          </div>`;
      } else if (group.type === 'person') {
        const dob = item.dob_year ? 'Born ' + item.dob_year : '';
        const country = item.country || '';
        const meta = [dob, country].filter(Boolean).join(' · ');
        leftHtml = `
          <div>
            <div class="name">${highlight(item.name, query)}</div>
            <div class="meta">${escapeHtml(meta)}</div>
          </div>`;
        rightHtml = `
          <div>
            <div class="stat">${formatNumber(item.controlled_count)}</div>
            <div class="stat-label">${item.controlled_count === 1 ? 'company' : 'companies'}</div>
          </div>`;
      } else if (group.type === 'address') {
        const town = item.town || '';
        leftHtml = `
          <div>
            <div class="name">${escapeHtml(item.premises || item.postcode)}</div>
            <div class="meta">${escapeHtml(item.postcode)}${town ? ' · ' + escapeHtml(town) : ''}</div>
          </div>`;
        rightHtml = `
          <div>
            <div class="stat">${formatNumber(item.reg_count)}</div>
            <div class="stat-label">registered</div>
          </div>`;
      } else if (group.type === 'title') {
        leftHtml = `
          <div>
            <div class="name">${escapeHtml(item.address || item.id)}</div>
            <div class="meta">${escapeHtml(item.id)}${item.postcode ? ' · ' + escapeHtml(item.postcode) : ''}${item.tenure ? ' · ' + escapeHtml(item.tenure) : ''}</div>
          </div>`;
        rightHtml = `
          <div>
            <div class="stat">→</div>
            <div class="stat-label">${escapeHtml(item.source)}</div>
          </div>`;
      }

      a.innerHTML = leftHtml + rightHtml;

      a.addEventListener('mouseenter', function () {
        clearActive();
        a.classList.add('active');
        activeIndex = parseInt(a.dataset.index, 10);
      });

      return a;
    }

    function clearActive() {
      allItems.forEach(function (el) { el.classList.remove('active'); });
    }

    function setActive(index) {
      if (allItems.length === 0) return;
      clearActive();
      if (index < 0) index = allItems.length - 1;
      if (index >= allItems.length) index = 0;
      activeIndex = index;
      allItems[index].classList.add('active');
      allItems[index].scrollIntoView({ block: 'nearest' });
    }

    function render(data) {
      dropdown.innerHTML = '';
      allItems = [];
      activeIndex = -1;

      if (!data || !data.groups || data.groups.length === 0) {
        dropdown.innerHTML = '<div class="empty">No results for &ldquo;' + escapeHtml(data.q || '') + '&rdquo;</div>';
        dropdown.classList.add('open');
        return;
      }

      data.groups.forEach(function (group) {
        const groupEl = document.createElement('div');
        groupEl.className = 'group';
        groupEl.innerHTML = '<div class="group-label">' + escapeHtml(group.label) + '</div>';
        group.results.forEach(function (item) {
          groupEl.appendChild(renderItem(group, item, data.q));
        });
        dropdown.appendChild(groupEl);
      });

      const footer = document.createElement('div');
      footer.className = 'footer';
      footer.innerHTML = '<a class="see-all" href="' + opts.resultsPath + '?q=' + encodeURIComponent(data.q) + '">See all results →</a>'
                       + '<span><span class="kbd">↵</span> to search</span>';
      dropdown.appendChild(footer);

      dropdown.classList.add('open');
    }

    function showLoading() {
      dropdown.innerHTML = '<div class="loading"><span class="spinner"></span>Searching…</div>';
      dropdown.classList.add('open');
    }

    function hide() {
      dropdown.classList.remove('open');
    }

    function fetchResults(query) {
      if (inflightController) {
        inflightController.abort();
      }
      inflightController = new AbortController();
      
      fetch(opts.endpoint + '?q=' + encodeURIComponent(query), {
        signal: inflightController.signal,
        headers: { 'Accept': 'application/json' },
      })
        .then(function (r) {
          if (!r.ok) throw new Error('Search failed');
          return r.json();
        })
        .then(function (data) {
          if (input.value === query) {
            render(data);
          }
        })
        .catch(function (err) {
          if (err.name === 'AbortError') return;
          dropdown.innerHTML = '<div class="empty">Search temporarily unavailable</div>';
          dropdown.classList.add('open');
        });
    }

    input.addEventListener('input', function () {
      const value = input.value.trim();
      
      if (clearBtn) {
        clearBtn.classList.toggle('visible', value.length > 0);
      }

      if (value.length < opts.minQueryLength) {
        hide();
        return;
      }
      if (value === lastQuery) return;
      lastQuery = value;

      if (debounceTimer) clearTimeout(debounceTimer);
      showLoading();
      debounceTimer = setTimeout(function () {
        fetchResults(value);
      }, opts.debounceMs);
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive(activeIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive(activeIndex - 1);
      } else if (e.key === 'Enter') {
        if (activeIndex >= 0 && allItems[activeIndex]) {
          window.location.href = allItems[activeIndex].href;
        } else {
          const value = input.value.trim();
          if (value) {
            window.location.href = opts.resultsPath + '?q=' + encodeURIComponent(value);
          }
        }
      } else if (e.key === 'Escape') {
        hide();
        input.blur();
      }
    });

    input.addEventListener('focus', function () {
      if (input.value.trim().length >= opts.minQueryLength) {
        if (input.value.trim() === lastQuery && dropdown.children.length > 0) {
          dropdown.classList.add('open');
        }
      }
    });

    document.addEventListener('click', function (e) {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        hide();
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        input.value = '';
        clearBtn.classList.remove('visible');
        hide();
        input.focus();
        lastQuery = '';
      });
    }

    // Keyboard shortcut: '/' to focus
    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        input.focus();
      }
    });
  };
})(window);
