# Media formatter via GitHub Actions

Deze repo bevat een workflow die je via `workflow_dispatch` kunt starten om een foto of video te schalen en bij te snijden naar 9:16 op 1080x1920 voor:
- tiktok
- instagram
- yt_shorts
- facebook

Output komt in de Actions run als artifact in de map `out/`.

## Inputs

- media_url: directe download URL naar een afbeelding of video
- platform: tiktok | instagram | yt_shorts | facebook
- mode: crop | pad
- focal_x: 0.0 tot 1.0 (default 0.5)
- focal_y: 0.0 tot 1.0 (default 0.5)
- filename: output naam zonder extensie (default output)

## Voorbeeld: workflow dispatch via GitHub API

Endpoint:
POST /repos/{owner}/{repo}/actions/workflows/format.yml/dispatches

Body:
{
  "ref": "main",
  "inputs": {
    "media_url": "https://example.com/video.mp4",
    "platform": "tiktok",
    "mode": "crop",
    "focal_x": "0.5",
    "focal_y": "0.4",
    "filename": "campaign_001"
  }
}

## n8n tip

Gebruik een HTTP Request node naar de GitHub endpoint met:
- Authorization: Bearer <token met workflow rechten>
- Accept: application/vnd.github+json
- Content-Type: application/json

Daarna kun je met de GitHub node of nog een HTTP Request node de artifacts ophalen van de run.