# Contributing to ASB Finstat

Thank you for your interest in contributing to **ASB Finstat**! We welcome contributions from developers, researchers, and financial data enthusiasts.

---

## 🚀 Quick Development Setup

1. **Fork and Clone the Repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/asb-finstat.git
   cd asb-finstat
   ```

2. **Backend Setup (Python 3.13 + FastAPI)**
   ```bash
   cd backend
   python -m venv .venv
   # Windows PowerShell:
   .\.venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   pip install -r requirements.txt
   copy .env.example .env
   ```

3. **Frontend Setup (Vite + React + TypeScript)**
   ```bash
   cd ../frontend
   npm install
   ```

4. **Launch Application**
   - **Windows:** `powershell -ExecutionPolicy Bypass -File .\startapp.ps1`
   - **Linux/macOS:** `./startapp.sh`

---

## 🧪 Testing Guidelines

Before submitting any pull request, make sure all tests and type checks pass.

- **Run Backend Unit Tests:**
  ```bash
  cd backend
  python -m unittest discover -s tests -v
  ```
- **Run Frontend Type Checks & Build:**
  ```bash
  cd frontend
  npx tsc --noEmit
  npm run build
  ```

---

## 📝 Pull Request Workflow

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Write clean, readable code with clear commit messages.
3. Verify tests and linting pass locally.
4. Ensure no secret API keys (such as `OPENROUTER_API_KEY`) are committed in code or logs.
5. Push your branch and open a Pull Request targeting `main`.

---

## ⚠️ Security & Secrets Notice

- **Never** commit `.env` files or API keys.
- If you notice a security issue, please review our [SECURITY.md](SECURITY.md) before reporting.
