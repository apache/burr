from burr.integrations.persisters.b_google_sheets import GoogleSheetsPersister

persister = GoogleSheetsPersister(
    spreadsheet_id="1ur4GqM0tQQyCRn3lAj5bZk3DAeZBvrbYRwKok780hHc",
    credentials_file="google_creds.json"
)

# Save some data
persister.save("demo_app", "user1", {"hello": "world"})

# Load the data
data = persister.load("demo_app", "user1")

print("Loaded data:", data)
print("App IDs:", persister.list_app_ids())