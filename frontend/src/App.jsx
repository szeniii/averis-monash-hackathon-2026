import { useEffect, useState } from "react";

function App() {
  const [emails, setEmails] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/emails")
      .then((response) => response.json())
      .then((data) => setEmails(data))
      .catch((error) => console.error("Failed to load emails:", error));
  }, []);

  return (
    <div>
      <h1>SDOC Verification Dashboard</h1>

      <p>Shipping Document Verification</p>

      <hr />

      <h2>Emails</h2>

      {emails.map((email) => (
        <button
          key={email.email_id}
          onClick={() => setSelectedEmail(email)}
        >
          {email.email_id}
        </button>
      ))}

      {selectedEmail && (
        <div>
          <hr />

          <h2>{selectedEmail.email_id}</h2>

          <p>
            <strong>Subject:</strong> {selectedEmail.subject}
          </p>

          <p>
            <strong>Body:</strong>
          </p>

          <p>{selectedEmail.body}</p>

          <p>
            <strong>Attachments:</strong>
          </p>

          <ul>
            {selectedEmail.attachments?.map((attachment) => (
              <li key={attachment}>{attachment}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default App;