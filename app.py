import os

from flask import Flask, render_template, request, jsonify
import pandas as pd
import pdfplumber
import numpy as np
import re
import io
from datetime import datetime
from sklearn.linear_model import LinearRegression

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

CATEGORY_KEYWORDS = {
    "Food": ["food", "restaurant", "swiggy", "zomato", "cafe",
             "pizza", "dominos", "burger", "grocery", "hotel"],
    "Travel": ["uber", "ola", "rapido", "petrol", "fuel", "irctc",
               "railway", "flight", "bus", "metro", "travel"],
    "Shopping": ["amazon", "flipkart", "myntra", "shopping",
                 "retail", "mall", "store"],
    "Bills": ["electricity", "water bill", "recharge", "airtel",
              "jio", "broadband", "internet", "utility", "bill"],
    "Entertainment": ["netflix", "spotify", "movie", "cinema",
                      "prime video", "gaming", "entertainment"],
    "Health": ["hospital", "pharmacy", "medical", "doctor",
               "medicine", "clinic", "health"],
    "Education": ["college", "school", "course", "books",
                  "education", "exam", "tuition"]
}


def categorize(description):
    text = str(description).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(word in text for word in keywords):
            return category
    return "Other"


def clean_amount(value):
    if pd.isna(value):
        return 0.0

    text = str(value).strip()
    if text.lower() in ["", "-", "nan", "none", "null"]:
        return 0.0

    negative = text.startswith("(") and text.endswith(")")
    text = (text.replace(",", "").replace("₹", "")
            .replace("INR", "").replace("Rs.", "")
            .replace("Rs", "").replace(" ", "").strip("()"))

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0

    amount = float(match.group())
    return -abs(amount) if negative else amount


def find_column(columns, keywords):
    for column in columns:
        name = re.sub(
            r"[^a-z0-9]+", " ",
            str(column).strip().lower()
        ).strip()

        if any(keyword in name for keyword in keywords):
            return column
    return None


def read_csv_file(file):
    raw = file.read()
    if not raw:
        raise ValueError("CSV file is empty.")

    for encoding in ["utf-8-sig", "cp1252", "latin1"]:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=encoding)
            if len(df.columns) < 2:
                continue
            return df
        except Exception:
            pass

    raise ValueError("Could not read CSV file.")


def read_pdf_file(file):
    tables, all_text = [], []

    with pdfplumber.open(io.BytesIO(file.read())) as pdf:
        for page in pdf.pages:
            all_text.append(page.extract_text() or "")
            tables.extend(page.extract_tables() or [])

    for table in tables:
        for index, row in enumerate(table[:4]):
            header = " ".join(str(x or "") for x in row).lower()

            if "date" in header and any(
                word in header for word in
                ["debit", "credit", "withdrawal", "deposit", "amount"]
            ):
                headers = [str(x or "").strip() for x in row]
                records = table[index + 1:]
                records = [
                    (list(r) + [None] * len(headers))[:len(headers)]
                    for r in records if r and any(str(x or "").strip() for x in r)
                ]

                if records:
                    return pd.DataFrame(records, columns=headers)

    pattern = re.compile(
        r"^\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
        r"\s+(.+?)\s+(-?[\d,]+\.\d{2})"
        r"(?:\s+(-?[\d,]+\.\d{2}))?"
        r"(?:\s+(-?[\d,]+\.\d{2}))?\s*$"
    )

    records = []
    for page in all_text:
        for line in page.splitlines():
            match = pattern.match(line)
            if match:
                date, description, amount, second, third = match.groups()
                records.append({
                    "Date": date,
                    "Description": description,
                    "Amount": amount
                })

    if records:
        return pd.DataFrame(records)

    raise ValueError(
        "No readable transaction table found in PDF. "
        "Try a text-based bank statement."
    )


def standardize_data(df):
    if df.empty:
        raise ValueError("No transactions found.")

    df.columns = [str(c).strip() for c in df.columns]
    columns = list(df.columns)

    date_col = find_column(columns, [
        "transaction date", "txn date", "date"
    ])
    description_col = find_column(columns, [
        "description", "narration", "particular",
        "transaction details", "remarks", "details",
        "merchant", "payee"
    ])
    debit_col = find_column(columns, [
        "debit", "withdrawal", "withdraw", "dr amount"
    ])
    credit_col = find_column(columns, [
        "credit", "deposit", "cr amount"
    ])
    amount_col = find_column(columns, [
        "transaction amount", "txn amount", "amount", "value"
    ])
    type_col = find_column(columns, [
        "transaction type", "dr cr", "type"
    ])

    if date_col is None:
        raise ValueError("Date column not found.")

    if description_col is None and len(columns) > 1:
        description_col = columns[1]

    if debit_col is None and credit_col is None and amount_col is None:
        raise ValueError("Debit, Credit, or Amount column not found.")

    dates = pd.to_datetime(
        df[date_col], errors="coerce", dayfirst=True
    )

    descriptions = (
        df[description_col].fillna("").astype(str)
        if description_col is not None
        else pd.Series("", index=df.index)
    )

    # Separate Debit/Credit columns take priority.
    if debit_col is not None or credit_col is not None:
        debits = (
            df[debit_col].apply(clean_amount).abs()
            if debit_col is not None
            else pd.Series(0.0, index=df.index)
        )
        credits = (
            df[credit_col].apply(clean_amount).abs()
            if credit_col is not None
            else pd.Series(0.0, index=df.index)
        )

        expenses = debits
        incomes = credits

    else:
        amounts = df[amount_col].apply(clean_amount)

        labels = descriptions.str.lower()
        if type_col is not None:
            labels = (
                df[type_col].fillna("").astype(str).str.lower()
                + " " + labels
            )

        is_debit = labels.str.contains(
            r"\bdebit\b|\bdr\b|withdraw|sent|paid|payment|purchase|spent|"
            r"money sent|upi out|transfer to",
            regex=True
        )

        is_credit = labels.str.contains(
            r"\bcredit\b|\bcr\b|deposit|received|credited|"
            r"money received|upi in|transfer from",
            regex=True
        )

        # Explicit transaction labels override amount signs.
        expenses = amounts.abs().where(
            is_debit,
            np.where(~is_credit & (amounts < 0), amounts.abs(), 0.0)
        )

        incomes = amounts.abs().where(
            is_credit,
            np.where(~is_debit & (amounts > 0), amounts.abs(), 0.0)
        )

    result = pd.DataFrame({
        "date": dates,
        "description": descriptions,
        "expense": expenses,
        "income": incomes
    })

    result = result.dropna(subset=["date"])
    result = result[
        (result["expense"] > 0) | (result["income"] > 0)
    ].copy()

    if result.empty:
        raise ValueError(
            "No valid transactions found. Check the date, amount, "
            "and debit/credit columns."
        )

    result["category"] = result["description"].apply(categorize)
    result["month"] = result["date"].dt.to_period("M").astype(str)

    return result.sort_values("date")


def predict_next_month(monthly_expenses):
    values = monthly_expenses.astype(float).values
    count = len(values)

    if count == 0:
        return 0, "No data", "No monthly expense data available."

    if count < 3:
        return round(max(0, float(np.mean(values))), 2), \
            "Average estimate", "Based on available months."

    x = np.arange(count).reshape(-1, 1)
    model = LinearRegression().fit(x, values)
    estimate = float(model.predict([[count]])[0])

    return round(max(0, estimate), 2), \
        "Linear Regression", "Based on historical monthly spending."


def analyze_transactions(data):
    total_income = round(float(data["income"].sum()), 2)
    total_expenses = round(float(data["expense"].sum()), 2)

    monthly = data.groupby("month").agg(
        income=("income", "sum"),
        expense=("expense", "sum")
    ).sort_index()

    months = pd.period_range(
        pd.Period(monthly.index.min(), freq="M"),
        pd.Period(monthly.index.max(), freq="M"),
        freq="M"
    ).astype(str)

    monthly = monthly.reindex(months, fill_value=0)

    forecast, model_name, note = predict_next_month(
        monthly["expense"]
    )

    categories = [
        {"category": name, "amount": round(float(amount), 2)}
        for name, amount in
        data.groupby("category")["expense"]
        .sum().sort_values(ascending=False).items()
    ]

    monthly_data = [
        {
            "month": month,
            "income": round(float(row["income"]), 2),
            "expense": round(float(row["expense"]), 2)
        }
        for month, row in monthly.iterrows()
    ]

    insights = []
    if len(monthly) >= 2:
        previous = float(monthly["expense"].iloc[-2])
        current = float(monthly["expense"].iloc[-1])

        if previous > 0:
            change = (current - previous) / previous * 100
            if change > 5:
                insights.append(f"Spending increased by {change:.1f}%.")
            elif change < -5:
                insights.append(f"Spending decreased by {abs(change):.1f}%.")
            else:
                insights.append("Spending was relatively stable.")

    if categories:
        top = categories[0]
        insights.append(
            f"{top['category']} is your largest expense category "
            f"at ₹{top['amount']:,.2f}."
        )

    if not insights:
        insights.append("Upload more months to identify spending patterns.")

    recent = []
    for _, row in data.tail(15).sort_values(
        "date", ascending=False
    ).iterrows():
        recent.append({
            "date": row["date"].strftime("%d %b %Y"),
            "description": str(row["description"])[:100],
            "category": row["category"],
            "expense": round(float(row["expense"]), 2),
            "income": round(float(row["income"]), 2)
        })

    next_month = str(pd.Period(monthly.index[-1], freq="M") + 1)

    return {
        "summary": {
            "income": total_income,
            "expenses": total_expenses,
            "net_cash_flow": round(total_income - total_expenses, 2),
            "transactions": int(len(data)),
            "months": int(len(monthly)),
            "first_month": str(monthly.index[0]),
            "last_month": str(monthly.index[-1])
        },
        "categories": categories,
        "monthly": monthly_data,
        "forecast": {
            "month": next_month,
            "base_estimate": forecast,
            "adjusted_estimate": forecast,
            "model": model_name,
            "note": note
        },
        "insights": insights,
        "recent_transactions": recent
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    if "statement" not in request.files:
        return jsonify({"error": "Please upload a statement."}), 400

    file = request.files["statement"]
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    filename = file.filename.lower()

    try:
        if filename.endswith(".csv"):
            raw_data = read_csv_file(file)
        elif filename.endswith(".pdf"):
            raw_data = read_pdf_file(file)
        else:
            return jsonify({
                "error": "Only CSV and PDF files are supported."
            }), 400

        transactions = standardize_data(raw_data)
        return jsonify(analyze_transactions(transactions))

    except Exception as error:
        return jsonify({"error": str(error)}), 400


@app.route("/forecast-adjust", methods=["POST"])
def forecast_adjust():
    payload = request.get_json(silent=True) or {}

    try:
        base = float(payload.get("base_estimate", 0))
        trip = float(payload.get("trip_budget", 0))
        festival = float(payload.get("festival_budget", 0))

        if not all(np.isfinite(v) and v >= 0
                   for v in [base, trip, festival]):
            raise ValueError

        return jsonify({
            "adjusted_estimate": round(base + trip + festival, 2)
        })

    except (ValueError, TypeError):
        return jsonify({
            "error": "Enter valid, non-negative budgets."
        }), 400


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "error": "File too large. Maximum upload size is 10 MB."
    }), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 1024)), debug=False)
