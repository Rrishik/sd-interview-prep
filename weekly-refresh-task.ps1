# Weekly System Design Harvest & Plan Refresh Script
# Runs every Sunday at 10:00 AM (when registered with Windows Task Scheduler)
# or manually via: pwsh -File d:\test\PersonalDocuments\sd-interview-prep\weekly-refresh-task.ps1

$ErrorActionPreference = 'Stop'
$PrepDir = 'd:\test\PersonalDocuments\sd-interview-prep'
$InboxFile = Join-Path $PrepDir 'inbox\manual-drops.md'
$DigestFile = Join-Path $PrepDir ("weekly-digest-" + (Get-Date -Format 'yyyy-MM-dd') + ".md")

$RepoSlug = 'Rrishik/sd-interview-prep'
$GhIssuesJson = Join-Path $PrepDir 'inbox\gh-open-issues.json'
try {
    gh issue list --repo $RepoSlug --state open --json number,title,body,createdAt,url | Set-Content -Path $GhIssuesJson -Encoding UTF8
} catch {
    "[]" | Set-Content -Path $GhIssuesJson -Encoding UTF8
}

$Prompt = @"
Run the weekly system design interview refresh in $PrepDir following weekly-refresh.md:
1. First, read $InboxFile ("Pending Drops") AND open GitHub Issues in $GhIssuesJson (from repo $RepoSlug). For any URLs, fetch the page; for any pasted raw text or issue body, parse the interview questions, company, level, and key takeaways, add them to sources.md and question-bank.md, move local items to "Processed Archive" in $InboxFile, and close processed GitHub issues with `gh issue close <number> --repo $RepoSlug --comment "Ingested into question-bank.md and sources.md"`.
2. Search recent (last 7 days) senior/L5/SDE2-3 system design & AI system design interview experiences from Reddit (r/ExperiencedDevs, r/leetcode), LeetCode Discuss, Hello Interview, and IGotAnOffer.
3. Append newly seen questions to question-bank.md and bump tallies.
4. Read progress.md weakness heat-map and compute Priority = Tally * (6 - WeaknessScore).
5. Write a concise ASD-STE100 digest to $DigestFile with:
   - Bookmarks & notes processed from GitHub Issues and inbox/manual-drops.md
   - New questions harvested from web search
   - Updated top-priority topics for next week
   - Recommended swaps in 00-plan.md
   - Spaced-repetition quiz questions due from progress.md
6. Rebuild the mobile web app by running `python build-site.py`.
"@

# Invoke GitHub Copilot CLI non-interactively to generate the weekly digest
copilot -p $Prompt
python (Join-Path $PrepDir 'build-site.py')
