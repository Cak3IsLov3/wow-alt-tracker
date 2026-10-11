// Tekent item level (linker as) en M+-score (rechter as, stippellijn) per week.
(async () => {
  const canvas = document.getElementById("history");
  if (!canvas || !window.Chart) return;

  const response = await fetch(`/api/history?ids=${canvas.dataset.ids}`);
  if (!response.ok) return;
  const data = await response.json();

  // Bij twee characters van dezelfde klasse valt de klassekleur samen.
  const fallback = ["#f8b700", "#3fc7eb", "#ff7c0a", "#aad372"];
  const seen = new Set();
  const datasets = data.series.flatMap((series, index) => {
    const color = seen.has(series.color) ? fallback[index % fallback.length] : series.color;
    seen.add(series.color);
    return [
      {
        label: `${series.name} – item level`,
        data: series.item_level,
        borderColor: color,
        backgroundColor: color,
        yAxisID: "ilvl",
        spanGaps: true,
        tension: 0.2,
      },
      {
        label: `${series.name} – M+-score`,
        data: series.mplus_score,
        borderColor: color,
        backgroundColor: color,
        borderDash: [6, 4],
        yAxisID: "score",
        spanGaps: true,
        tension: 0.2,
      },
    ];
  });

  const grid = { color: "rgba(255,255,255,0.08)" };
  const ticks = { color: "#9aa3b2" };
  new Chart(canvas, {
    type: "line",
    data: { labels: data.labels, datasets },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: "#e6e8ee" } } },
      scales: {
        x: { grid, ticks },
        ilvl: { position: "left", grid, ticks, title: { display: true, text: "Item level", color: "#9aa3b2" } },
        score: {
          position: "right",
          grid: { drawOnChartArea: false },
          ticks,
          title: { display: true, text: "M+-score", color: "#9aa3b2" },
        },
      },
    },
  });
})();
