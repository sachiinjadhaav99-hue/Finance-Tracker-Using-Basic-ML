let monthlyChart = null;
let categoryChart = null;
let currentReport = null;

const money = value =>
    new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 0
    }).format(Number(value) || 0);

document.getElementById("today").textContent =
    new Date().toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric"
    });

function showStatus(message, type = "") {
    const element = document.getElementById("statusMessage");
    element.textContent = message;
    element.className = "status-message " + type;
}

function makeElement(tag, className, text) {
    const element = document.createElement(tag);

    if (className) {
        element.className = className;
    }

    if (text !== undefined) {
        element.textContent = text;
    }

    return element;
}


// -----------------------------
// UPLOAD AND ANALYZE STATEMENT
// -----------------------------

document.getElementById("uploadForm").addEventListener(
    "submit",
    async function (event) {
        event.preventDefault();

        const fileInput = document.getElementById("statement");
        const button = document.getElementById("uploadButton");
        const file = fileInput.files[0];

        if (!file) {
            showStatus("Please choose a CSV or PDF file.", "error");
            return;
        }

        const extension = file.name.split(".").pop().toLowerCase();

        if (!["csv", "pdf"].includes(extension)) {
            showStatus("Only CSV and PDF files are supported.", "error");
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            showStatus("File must be smaller than 10 MB.", "error");
            return;
        }

        const formData = new FormData();
        formData.append("statement", file);

        button.disabled = true;
        button.textContent = "Analyzing...";
        showStatus("Reading transactions and analyzing spending...");

        try {
            const response = await fetch("/analyze", {
                method: "POST",
                body: formData
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    result.error || "Could not analyze statement."
                );
            }

            currentReport = result;
            renderDashboard(result);

            showStatus(
                "Analysis complete. " +
                result.summary.transactions +
                " transactions processed.",
                "success"
            );

        } catch (error) {
            showStatus(error.message, "error");
        } finally {
            button.disabled = false;
            button.textContent = "Analyze Statement";
        }
    }
);


// -----------------------------
// DISPLAY DASHBOARD
// -----------------------------

function renderDashboard(report) {
    const summary = report.summary;

    document.getElementById("dashboardContent").hidden = false;

    document.getElementById("totalIncome").textContent =
        money(summary.income);

    document.getElementById("totalExpenses").textContent =
        money(summary.expenses);

    document.getElementById("netCashFlow").textContent =
        money(summary.net_cash_flow);

    const cashFlowElement = document.getElementById("netCashFlow");
    cashFlowElement.style.color =
        summary.net_cash_flow < 0 ? "#dc2626" : "#16865b";

    document.getElementById("predictedExpense").textContent =
        money(report.forecast.base_estimate);

    document.getElementById("predictionMonth").textContent =
        "Forecast for " + report.forecast.month;

    document.getElementById("baseForecast").textContent =
        money(report.forecast.base_estimate);

    document.getElementById("adjustedForecast").textContent =
        money(report.forecast.adjusted_estimate);

    document.getElementById("forecastNote").textContent =
        report.forecast.model + ": " + report.forecast.note;

    renderMonthlyChart(report.monthly);
    renderCategoryChart(report.categories);
    renderInsights(report.insights);
    renderTransactions(report.recent_transactions, summary.transactions);

    document.getElementById("dashboardContent").scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}


// -----------------------------
// MONTHLY CHART
// -----------------------------

function renderMonthlyChart(monthly) {
    const canvas = document.getElementById("monthlyChart");

    if (monthlyChart) {
        monthlyChart.destroy();
    }

    monthlyChart = new Chart(canvas, {
        type: "bar",
        data: {
            labels: monthly.map(item => item.month),
            datasets: [
                {
                    label: "Income",
                    data: monthly.map(item => item.income),
                    backgroundColor: "#0d9488",
                    borderRadius: 5
                },
                {
                    label: "Expenses",
                    data: monthly.map(item => item.expense),
                    backgroundColor: "#f59e0b",
                    borderRadius: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "bottom"
                },
                tooltip: {
                    callbacks: {
                        label: context =>
                            context.dataset.label + ": " +
                            money(context.raw)
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: value => money(value)
                    }
                }
            }
        }
    });
}


// -----------------------------
// CATEGORY CHART
// -----------------------------

function renderCategoryChart(categories) {
    const canvas = document.getElementById("categoryChart");

    if (categoryChart) {
        categoryChart.destroy();
    }

    const usableCategories = categories.filter(
        item => item.amount > 0
    );

    categoryChart = new Chart(canvas, {
        type: "doughnut",
        data: {
            labels: usableCategories.map(item => item.category),
            datasets: [{
                data: usableCategories.map(item => item.amount),
                backgroundColor: [
                    "#0d9488",
                    "#f59e0b",
                    "#6366f1",
                    "#ec4899",
                    "#14b8a6",
                    "#f97316",
                    "#64748b",
                    "#a78bfa"
                ],
                borderWidth: 2,
                borderColor: "#ffffff"
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "62%",
            plugins: {
                legend: {
                    position: "bottom"
                },
                tooltip: {
                    callbacks: {
                        label: context =>
                            context.label + ": " + money(context.raw)
                    }
                }
            }
        }
    });
}


// -----------------------------
// SPENDING INSIGHTS
// -----------------------------

function renderInsights(insights) {
    const container = document.getElementById("insightsList");
    container.replaceChildren();

    insights.forEach(message => {
        const item = makeElement("div", "insight-item", "✦  " + message);
        container.appendChild(item);
    });
}


// -----------------------------
// RECENT TRANSACTIONS
// -----------------------------

function renderTransactions(transactions, totalCount) {
    const tbody = document.getElementById("transactionTable");
    tbody.replaceChildren();

    document.getElementById("transactionCount").textContent =
        totalCount + " transactions detected · Showing latest 15";

    transactions.forEach(transaction => {
        const row = document.createElement("tr");

        row.appendChild(makeElement("td", "", transaction.date));

        row.appendChild(
            makeElement("td", "", transaction.description)
        );

        row.appendChild(
            makeElement("td", "", transaction.category)
        );

        row.appendChild(
            makeElement(
                "td",
                transaction.expense > 0 ? "negative" : "",
                transaction.expense > 0
                    ? money(transaction.expense)
                    : "—"
            )
        );

        row.appendChild(
            makeElement(
                "td",
                transaction.income > 0 ? "positive" : "",
                transaction.income > 0
                    ? money(transaction.income)
                    : "—"
            )
        );

        tbody.appendChild(row);
    });
}


// -----------------------------
// FESTIVAL AND TRIP ADJUSTMENT
// -----------------------------

document.getElementById("adjustButton").addEventListener(
    "click",
    async function () {
        if (!currentReport) {
            showStatus("Upload a statement first.", "error");
            return;
        }

        const trip = Number(
            document.getElementById("tripBudget").value
        );

        const festival = Number(
            document.getElementById("festivalBudget").value
        );

        if (
            !Number.isFinite(trip) ||
            !Number.isFinite(festival) ||
            trip < 0 ||
            festival < 0
        ) {
            showStatus(
                "Please enter valid, non-negative budgets.",
                "error"
            );
            return;
        }

        try {
            const response = await fetch("/forecast-adjust", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    base_estimate:
                        currentReport.forecast.base_estimate,
                    trip_budget: trip,
                    festival_budget: festival
                })
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || "Adjustment failed.");
            }

            document.getElementById("adjustedForecast").textContent =
                money(result.adjusted_estimate);

            currentReport.forecast.adjusted_estimate =
                result.adjusted_estimate;

            showStatus("Forecast updated successfully.", "success");

        } catch (error) {
            showStatus(error.message, "error");
        }
    }
);