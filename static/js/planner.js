const plansGrid = document.getElementById("plans-grid");
const sortButtons = document.querySelectorAll("[data-sort-buttons] .sort-button");

if (plansGrid && sortButtons.length) {
  const cards = Array.from(plansGrid.querySelectorAll(".plan-card"));

  const sortCards = (mode) => {
    const sorted = [...cards].sort((a, b) => {
      const left = Number(a.dataset[mode]);
      const right = Number(b.dataset[mode]);
      if (left === right) {
        const altMode = mode === "cost" ? "duration" : "cost";
        return Number(a.dataset[altMode]) - Number(b.dataset[altMode]);
      }
      return left - right;
    });
    sorted.forEach((card) => plansGrid.appendChild(card));
    sortButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.sort === mode));
  };

  sortButtons.forEach((button) => {
    button.addEventListener("click", () => sortCards(button.dataset.sort));
  });
}
