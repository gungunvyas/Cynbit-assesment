# TenantEase – AI-Assisted Maintenance Desk

TenantEase is a Streamlit-based property maintenance management application that helps tenants report maintenance issues and allows landlords to track, prioritize, and manage repair requests efficiently.

The application uses AI-assisted issue categorization and urgency assessment through the JEV API, with a rule-based fallback when the AI service is unavailable.

## 🌐 Live Demo

🚀 **[Click here to view TenantEase](https://tenant-ease-jev-based-maintenance-feature.streamlit.app)**

> Replace the placeholder URL with your deployed Streamlit Community Cloud URL.

## ✨ Features

### 👤 Tenant Dashboard
- Submit maintenance requests for individual units or common areas.
- Upload supporting photos and videos.
- Track the status of submitted maintenance tickets.
- View maintenance request history.
- Confirm completed repairs.
- Reopen resolved requests if the issue persists.

### 🏢 Landlord Dashboard
- View all maintenance requests in one place.
- Monitor pending, in-progress, and resolved tickets.
- Filter and manage maintenance requests.
- Identify overdue maintenance requests.
- Update ticket statuses.
- View ticket activity and status history.
- Identify potentially duplicate complaints.

### 🤖 AI-Powered Maintenance Triage
- Automatically categorize maintenance complaints.
- Assess urgency based on the reported issue.
- Support multiple maintenance categories.
- Use rule-based classification as a fallback when the AI service is unavailable.
- Apply safety-related urgency overrides for potentially critical issues.

### 🗄️ Database Management
- SQLite database integration.
- Store tenant, landlord, building, unit, and lease information.
- Maintain maintenance ticket records.
- Store attachment information.
- Track ticket events and status changes.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend development |
| Streamlit | Web application interface |
| SQLite | Database management |
| HTTPX | API communication |
| python-dotenv | Environment variable management |
| JEV API | AI-assisted maintenance triage |

## 📂 Project Structure

```text
TenantEase/
│
├── app.py
│
├── Maintenance/
│   └── backend/
│       ├── __init__.py
│       ├── database.py
│       └── services.py
│
├── requirements.txt
├── .env
└── README.md
```

Make sure the folder structure matches the imports used in `app.py`, or adjust the imports accordingly.

## ⚙️ Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/your-repository.git
```

### 2. Navigate to the Project Directory

```bash
cd your-repository
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

If you do not have a `requirements.txt` file, create one with:

```text
streamlit
httpx
python-dotenv
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
JEV_BASE_URL=your_jev_api_base_url
JEV_API_KEY=your_jev_api_key
```

The JEV API configuration is optional. The application includes a rule-based fallback for maintenance classification.

### 5. Run the Application

```bash
streamlit run app.py
```

The application will be available locally at:

```text
http://localhost:8501
```

## ☁️ Deployment

TenantEase is deployed using **Streamlit Community Cloud**.

To deploy your own instance:

1. Push your project to a GitHub repository.
2. Visit [Streamlit Community Cloud](https://share.streamlit.io/).
3. Connect your GitHub account.
4. Select your repository.
5. Choose `app.py` as the main application file.
6. Configure the required environment variables under Streamlit Secrets.
7. Deploy the application.

For Streamlit Secrets, use:

```toml
JEV_BASE_URL = "your_jev_api_base_url"
JEV_API_KEY = "your_jev_api_key"
```

## 🔄 Maintenance Ticket Lifecycle

A maintenance request generally follows this workflow:

1. Tenant submits a maintenance complaint.
2. The application categorizes the issue and assesses its urgency.
3. Landlord reviews the submitted request.
4. Landlord updates the ticket status as work progresses.
5. Tenant confirms the repair after completion.
6. Tenant can reopen the ticket if the issue is not resolved.

## ⚠️ Important Notes

- This project is a prototype / proof of concept.
- The application uses simulated login and demo role selection.
- It does not currently implement production-grade authentication.
- SQLite is used for database storage.
- Uploaded attachment data is stored in SQLite.
- Streamlit Community Cloud deployments may not provide durable local SQLite storage across restarts, rebuilds, or redeployments.
- For production use, consider a managed persistent database, dedicated object storage, and proper authentication.
- AI-generated urgency assessments should not replace professional judgment or emergency response procedures.

## 🔮 Future Improvements

- Implement secure user authentication and role-based access control.
- Integrate a cloud-hosted persistent database.
- Add email and notification support.
- Introduce maintenance analytics and reporting.
- Improve duplicate complaint detection.
- Add cloud-based attachment storage.
- Expand AI-powered maintenance insights.

## 👩‍💻 Author

**Gungun Vyas**

## 📄 License

This project is available for educational and demonstration purposes. Add an appropriate open-source license if you intend to distribute it under specific reuse terms.
