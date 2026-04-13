const financeDataNode = document.getElementById("finance-data");

if (financeDataNode && window.Chart) {
  const financeData = JSON.parse(financeDataNode.textContent);

  const weeklyCanvas = document.getElementById("weekly-chart");
  const monthlyCanvas = document.getElementById("monthly-chart");

  if (weeklyCanvas) {
    new Chart(weeklyCanvas, {
      type: "bar",
      data: {
        labels: financeData.weekly_points.map((point) => point.label),
        datasets: [
          {
            label: "Weekly spend",
            data: financeData.weekly_points.map((point) => point.amount),
            backgroundColor: financeData.weekly_points.map((point) =>
              point.amount <= financeData.budget ? "#8FAF8C" : "#C86030"
            ),
            borderRadius: 10,
          },
          {
            label: "Budget",
            data: financeData.weekly_points.map(() => financeData.budget),
            type: "line",
            borderColor: "#D4AE3A",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.25,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#FFFFFF" } } },
        scales: {
          x: { ticks: { color: "#89C4E1" }, grid: { color: "rgba(137, 196, 225, 0.08)" } },
          y: { ticks: { color: "#89C4E1" }, grid: { color: "rgba(137, 196, 225, 0.08)" } },
        },
      },
    });
  }

  if (monthlyCanvas) {
    new Chart(monthlyCanvas, {
      type: "line",
      data: {
        labels: financeData.monthly_points.map((point) => point.label),
        datasets: [
          {
            label: "Monthly spend",
            data: financeData.monthly_points.map((point) => point.amount),
            borderColor: "#89C4E1",
            backgroundColor: "rgba(137, 196, 225, 0.18)",
            fill: true,
            tension: 0.35,
            pointBackgroundColor: "#D4AE3A",
            pointBorderColor: "#D4AE3A",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#FFFFFF" } } },
        scales: {
          x: { ticks: { color: "#89C4E1" }, grid: { color: "rgba(137, 196, 225, 0.08)" } },
          y: { ticks: { color: "#89C4E1" }, grid: { color: "rgba(137, 196, 225, 0.08)" } },
        },
      },
    });
  }
}
