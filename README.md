# My Finances 💸

> **Understand your money. Plan your future.**

My Finances is a comprehensive, multi-user personal finance management web application. It goes beyond simple expense tracking by offering smart budgeting, goal tracking, loan/EMI management, recurring bills, a proprietary "Money Score", and AI-powered financial insights.

---

## ✨ Credits & Acknowledgements

* **AI Assistance:** This application was developed from scratch with the assistance of **ChatGPT** and **Google Antigravity**.
* **Design:** The gorgeous, calming pastel color palette was carefully curated and selected using **Coolors**.

---

## 🚀 Features

### 📊 Core Tracking
* **Multi-User Authentication:** Secure signup, login, and password reset (with SMTP email support).
* **Transactions:** Track income and expenses with detailed categories, notes, and payment methods. Includes full search and filtering capabilities.
* **Custom Categories:** Users can add and manage their own custom income and expense categories.
* **Currency Preferences:** Support for local currencies (defaults to ₹).

### 🎯 Planning & Budgeting
* **Budgets:** Set monthly limits per category and track your spend percentage.
* **Savings Goals:** Define target amounts and dates, and track your progress visually.
* **Loans & EMIs:** Track active loans, principal amounts, and log your EMI payments to watch your remaining balance drop.
* **Recurring Bills:** Manage monthly/yearly subscriptions and get alerted when they are due.

### 🧠 Smart Insights & Analytics
* **Money Score:** A gamified 0–1000 score evaluating your financial health based on savings rate, budget adherence, and goal progress.
* **Financial Insights (AI):** Uses Google's Gemini API to generate concise, personalized summaries of your monthly spending habits. (Includes a deterministic fallback engine if AI is unavailable).
* **Smart Alerts:** A built-in notification engine that warns you about upcoming bills, over-budget categories, and month-over-month spending spikes.
* **Affordability Calculator:** Ask the app if you can afford a specific purchase based on your current balance and upcoming obligations for the month.
* **Data Visualization:** Interactive charts showing category breakdowns, 6-month trends, daily money flow, and month-over-month comparisons.
* **Net Worth Tracker:** Log and track assets versus liabilities.

### 💾 Data Management
* **Export:** Export transactions to CSV, or download a full JSON backup of your entire financial profile.
* **Import:** Restore your data from a JSON backup.

---

## 🛠️ Tech Stack

* **Backend:** Python, Flask
* **Database:** PostgreSQL (requires `DATABASE_URL` environment variable)
* **Frontend:** HTML5, Jinja2 Templates
* **Styling:** Tailwind CSS (via CDN)
* **Reactivity:** Alpine.js (Lightweight JavaScript framework)
* **Charts:** Chart.js
* **Icons:** Phosphor Icons

---

## ⚙️ Installation & Setup

### Prerequisites
* Python 3.8 or higher installed on your system.

### Running Locally

1. **Clone or download the repository.**
2. **Set up a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: `venv\Scripts\activate`
   ```
3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the application:**
   You can simply double-click the `run.bat` file (on Windows), or run:
   ```bash
   python app.py
   ```
5. **Open your browser:**
   Navigate to `http://127.0.0.1:5000`

---

## 🔧 Configuration (Environment Variables)

The application uses environment variables for external services. If these are not set, the app will gracefully fall back to local/offline alternatives.

### 1. PostgreSQL Database (Required)

To run the application, you must provide a valid PostgreSQL connection string. 

**For Render Deployment:**
1. Create a "PostgreSQL" service on Render.
2. In your Flask Web Service, add an environment variable `DATABASE_URL` and set its value to your PostgreSQL Internal Database URL (e.g. `postgresql://user:pass@host/dbname`).
3. The app will automatically create all necessary tables upon starting up. No manual migration is needed.

**For Local Development:**
```powershell
[System.Environment]::SetEnvironmentVariable("DATABASE_URL", "postgresql://postgres:password@localhost:5432/myfinances", "User")
```

### 2. AI Financial Insights (Google Gemini)

To enable AI summaries on the dashboard:

* Get a free API key from [Google AI Studio](https://aistudio.google.com/).
* Set it in your terminal before running the app:

  ```powershell
  [System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your_api_key", "User")
  ```

### 2. Password Reset Emails (SMTP)

To allow the app to actually send password reset emails (e.g., using Gmail):

* Generate an "App Password" in your Google Account security settings.
* Set the following variables:

  ```powershell
  [System.Environment]::SetEnvironmentVariable("SMTP_USER", "your-email@gmail.com", "User")
  [System.Environment]::SetEnvironmentVariable("SMTP_PASS", "your-app-password", "User")
  ```

*(Note: If SMTP is not configured, the app will safely print the password reset link directly on the screen for local testing).*

---

## 📂 Project Structure

```text
📁 My Finances/
├── 📄 app.py               # Main Flask application and routes
├── 📄 database.py          # PostgreSQL connection wrapper and auto-init
├── 📄 schema.pg.sql        # PostgreSQL table definitions
├── 📄 requirements.txt     # Python dependencies (psycopg2-binary, flask, etc)
├── 📄 run.bat              # Windows startup script
└── 📁 templates/           # HTML templates (Jinja2)
    ├── base.html           # Main layout & sidebar navigation
    ├── dashboard.html      # Overview, score, and insights
    ├── transactions.html   # Income/Expense tracking
    ├── budgets.html        # Category limits
    └── ...                 # Other feature templates
```

---

*Built with ❤️ for better personal finance.*
