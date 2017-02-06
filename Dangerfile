# Add a CHANGELOG entry for app changes
if !git.modified_files.include?("CHANGELOG.md") && has_app_changes
  fail("Please include a CHANGELOG entry.")
  message "See http://keepachangelog.com/en/0.3.0/ for details on good changelog guidelines"
end
