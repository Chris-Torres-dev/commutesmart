const budgetForm = document.getElementById("budget-form");
const spendForm = document.getElementById("spend-form");
const exportButton = document.getElementById("export-button");
const exportOutput = document.getElementById("export-output");
const presetButtons = document.querySelectorAll(".budget-preset");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");

const refreshMetrics = (finance) => {
  const week = document.querySelector("[data-metric-week]");
  const month = document.querySelector("[data-metric-month]");
  const semester = document.querySelector("[data-metric-semester]");
  const saved = document.querySelector("[data-metric-saved]");
  const percent = document.querySelector("[data-budget-percent]");

  if (week) week.textContent = `$${Math.round(finance.metrics.week)}`;
  if (month) month.textContent = `$${Math.round(finance.metrics.month)}`;
  if (semester) semester.textContent = `$${Math.round(finance.metrics.semester)}`;
  if (saved) saved.textContent = `$${Math.round(finance.metrics.saved)}`;
  if (percent) percent.textContent = `${finance.budget_status.percent}% used`;
};

presetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const budgetInput = budgetForm?.querySelector("input[name='weekly_budget']");
    if (budgetInput) budgetInput.value = button.dataset.budget;
  });
});

if (budgetForm) {
  budgetForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(budgetForm);
    const payload = {
      weekly_budget: Number(formData.get("weekly_budget")),
      budget_alert_50: formData.get("budget_alert_50") === "on",
      budget_alert_80: formData.get("budget_alert_80") === "on",
    };

    const response = await fetch("/api/budget", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken || "" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (data.finance) refreshMetrics(data.finance);
  });
}

if (spendForm) {
  spendForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(spendForm);
    const payload = {
      amount: Number(formData.get("amount")),
      transport_mode: formData.get("transport_mode"),
      notes: formData.get("notes"),
    };

    const response = await fetch("/api/spend-log", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken || "" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (data.finance) {
      refreshMetrics(data.finance);
      window.location.reload();
    }
  });
}

if (exportButton && exportOutput) {
  exportButton.addEventListener("click", async () => {
    const response = await fetch("/api/export");
    const data = await response.json();
    exportOutput.value = data.text || "";
  });
}
