---
layout: single
title: "Publications"
permalink: /publications/
author_profile: true
---

<input type="text" id="pub-search" placeholder="Search by title, author, journal, or year…"
  style="width:100%; padding:8px 12px; margin-bottom:1.5em; font-size:1em;
         border:1px solid #ccc; border-radius:4px; box-sizing:border-box;">

<script>
(function () {
  // Move search box above the page h1 title
  var input = document.getElementById('pub-search');
  if (input) {
    var h1 = document.querySelector('.page__content h1, article h1, h1.page__title, h1');
    if (h1 && h1.parentNode) {
      h1.parentNode.insertBefore(input, h1);
    }
  }

  input = document.getElementById('pub-search');
  if (!input) return;

  input.addEventListener('input', function () {
    var query = this.value.toLowerCase().trim();

    // jekyll-scholar with group_by:year renders pairs of:
    //   <h2 class="bibliography">YEAR</h2>
    //   <ol class="bibliography">...</ol>
    var headers = document.querySelectorAll('h2.bibliography');
    var lists   = document.querySelectorAll('ol.bibliography');

    lists.forEach(function (ol, i) {
      var items = ol.querySelectorAll('li');
      var visibleCount = 0;

      items.forEach(function (li) {
        var text = li.textContent.toLowerCase();
        var match = !query || text.indexOf(query) !== -1;
        li.style.display = match ? '' : 'none';
        if (match) visibleCount++;
      });

      // hide the year heading when no entries are visible
      if (headers[i]) {
        headers[i].style.display = visibleCount > 0 ? '' : 'none';
      }
    });
  });
})();
</script>

{% bibliography %}


