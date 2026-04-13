const shell = document.querySelector(".onboarding-shell");

if (shell) {
  const previewCheapest = shell.querySelector(".preview-cheapest");
  const previewSuggested = shell.querySelector(".preview-suggested");
  const form = shell.querySelector("[data-onboarding-preview]");
  const schoolButtons = shell.querySelectorAll(".school-choice");
  const budgetInputs = shell.querySelectorAll("input[name='budget_choice']");
  const customBudget = shell.querySelector("input[name='custom_budget']");
  const dayRange = shell.querySelector("input[name='days_per_week']");
  const rangeOutput = shell.querySelector(".range-output");

  const getSelectedModes = () => {
    const checked = Array.from(shell.querySelectorAll("input[name='transport_modes']:checked"));
    return checked.map((input) => input.value);
  };

  const estimateWeeklyCost = () => {
    const days = Number(shell.querySelector("input[name='days_per_week']")?.value || 4);
    const trips = Number(shell.querySelector("select[name='trips_per_day']")?.value || 2);
    const modes = getSelectedModes();

    const transit = Math.min(34, 2.9 * days * trips);
    const bike = days >= 4 ? 17.99 / 4.33 : Math.min(days * 15, days * trips * 4.49);
    const car = days * trips * 4.75 + days * 15;

    const options = [];
    if (modes.includes("subway") || modes.includes("bus") || !modes.length) options.push(transit);
    if (modes.includes("bike")) options.push(bike);
    if (modes.includes("car")) options.push(car);

    const cheapest = Math.round((Math.min(...options) || transit) * 100) / 100;
    const suggested = Math.max(34, Math.round((cheapest + 5) * 100) / 100);
    return { cheapest, suggested };
  };

  const syncPreview = () => {
    const { cheapest, suggested } = estimateWeeklyCost();
    if (previewCheapest) previewCheapest.textContent = `$${Math.round(cheapest)}/week`;
    if (previewSuggested) previewSuggested.textContent = `$${Math.round(suggested)}/week`;
  };

  schoolButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nameInput = shell.querySelector("input[name='school_name']");
      const addressInput = shell.querySelector("input[name='school_address']");
      if (nameInput) nameInput.value = button.dataset.schoolName || "";
      if (addressInput) addressInput.value = button.dataset.schoolAddress || "";
    });
  });

  budgetInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (customBudget) {
        customBudget.disabled = input.value !== "custom" || !input.checked;
      }
    });
  });

  if (dayRange && rangeOutput) {
    dayRange.addEventListener("input", () => {
      rangeOutput.textContent = `${dayRange.value} days`;
      syncPreview();
    });
  }

  form?.addEventListener("input", syncPreview);
  syncPreview();
}
