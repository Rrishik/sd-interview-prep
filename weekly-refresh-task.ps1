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
    gh issue list --repo $RepoSlug --state all --limit 100 --json number,title,body,state,labels,comments,createdAt,url | Set-Content -Path $GhIssuesJson -Encoding UTF8
} catch {
    "[]" | Set-Content -Path $GhIssuesJson -Encoding UTF8
}

$Prompt = @"
Run the weekly system design refresh in $PrepDir following weekly-refresh.md:
1. Answer Inline Chapter Questions (`line-question` issues):
   - Inspect $GhIssuesJson for issues with label `line-question` that are either open OR have a latest comment from the user waiting for a reply.
   - Read the referenced chapter in `chapters/*.md` matching the `<!-- anchor:chXX-bYY -->` tag.
   - Post a clear, first-principles Wait But Why x ByteByteGo reply on the issue thread via `gh issue comment <number> --repo $RepoSlug --body "<answer>"`. If the question clarifies a gap in the chapter, also update the corresponding `chapters/chXX-*.md` file.
2. Process New Sources (`inbox` issues + $InboxFile):
   - For open issues labeled `inbox` and items in $InboxFile ("Pending Drops"), fetch URLs, add citations to the relevant `chapters/chXX-*.md` "Sources & References" section (and `sources.md`), and close processed `inbox` issues with `gh issue close <number> --repo $RepoSlug --comment "Added to chapter references"`.
3. Harvest Web Sources (last 7 days) from Reddit (r/ExperiencedDevs, r/leetcode), LeetCode Discuss, Hello Interview, and ByteByteGo, and fold high-signal architecture patterns or citations into `chapters/*.md`.
4. Rebuild the diagrams and blog by running `python build-diagrams.py` and `python build-site.py`, then commit and push `chapters/`, `diagrams/`, and `docs/index.html` to `origin/main`.
"@

# Invoke GitHub Copilot CLI non-interactively to generate the weekly digest
copilot -p $Prompt
python (Join-Path $PrepDir 'build-site.py')
