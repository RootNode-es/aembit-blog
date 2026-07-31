// client-app.js
const express = require("express")
const crypto = require("crypto")

const app = express()
app.use(express.urlencoded({ extended: true })) // needed to read the button's form POST
const PORT = 8000

const CLIENT_ID = "CLIENT_ID"
const CLIENT_SECRET = "CLIENT_SECRET"
const REDIRECT_URI = "http://localhost:8000/callback" // must exactly match what you registered

const GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

const pendingStates = new Set()

// First endpoint: Client home page, redirects to Github credentials page (Step 3)
app.get("/", (req, res) => {
  const state = crypto.randomBytes(8).toString("hex")
  pendingStates.add(state)

  const url = new URL(GITHUB_AUTHORIZE_URL)
  url.searchParams.set("client_id", CLIENT_ID)
  url.searchParams.set("redirect_uri", REDIRECT_URI)
  url.searchParams.set("scope", "read:user") // just enough to read the profile
  url.searchParams.set("state", state)

  console.log("\n=== Step 3: sending user to GitHub's /authorize ===")
  console.log("client_id     :", CLIENT_ID)
  console.log("redirect_uri  :", REDIRECT_URI)
  console.log("scope         :", "read:user")
  console.log(
    "state (ours)  :",
    state,
    "  <- generated now, must come back unchanged in Step 5",
  )
  console.log("full authorize URL:", url.toString())

  res.send(`<a href="${url.toString()}">Log in with GitHub</a>`)
})

// Second endpoint: callback. Authorization Server returns here with an Authorization Code
app.get("/callback", async (req, res) => {
  const { code, state, error, error_description } = req.query

  console.log("\n=== Step 4: GitHub redirected back to /callback ===")
  console.log(
    "authorization code:",
    code,
    "  <- short-lived, single-use, NOT exchanged yet",
  )
  console.log("state (returned)  :", state)

  if (error) {
    console.log(
      "GitHub returned an error instead of a code:",
      error,
      error_description,
    )
    return res
      .status(400)
      .send(`GitHub denied authorization: ${error_description || error}`)
  }
  if (!state || !pendingStates.has(state)) {
    console.log("STATE MISMATCH — rejecting, possible CSRF")
    return res
      .status(400)
      .send("Invalid or missing state — possible CSRF, aborting.")
  }
  console.log("state check passed — matches the value generated in Step 3")
  pendingStates.delete(state)

  res.send(`
    <h2>Step 5 complete</h2>
    <p>GitHub redirected the browser back here with an authorization code:</p>
    <pre>${code}</pre>
    <p>Clicking the button below to trade this authorization code for an access token.</p>
    <form method="POST" action="/exchange-token">
      <input type="hidden" name="code" value="${code}" />
      <button type="submit">Exchange code for access token</button>
    </form>
  `)
})

// Third endpoint: Exchange Token. When accessed, exchanges an Authorization code for an Access Token (steps 6 and 7)
app.post("/exchange-token", async (req, res) => {
  const { code } = req.body

  console.log(
    "\n=== Starting step 6: exchanging the code for a token (server-to-server) ===",
  )
  console.log("POST", GITHUB_TOKEN_URL)
  console.log("sending code       :", code)
  console.log("sending client_id  :", CLIENT_ID)
  console.log(
    "sending client_secret:",
    CLIENT_SECRET.slice(0, 4) + "…redacted…",
    " <- never logged in full, never sent to the browser",
  )

  const tokenRes = await fetch(GITHUB_TOKEN_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: new URLSearchParams({
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      code,
      redirect_uri: REDIRECT_URI,
    }),
  })

  const tokens = await tokenRes.json()

  if (tokens.error) {
    console.log("token exchange FAILED:", tokens)
    return res
      .status(400)
      .send(`Token exchange failed: ${JSON.stringify(tokens)}`)
  }

  console.log("access_token received:", tokens.access_token)
  console.log("token_type           :", tokens.token_type)
  console.log("scope granted        :", tokens.scope)

  res.send(`
    <h2>Step 7 complete</h2>
    <p>Token response from GitHub's /login/oauth/access_token:</p>
    <pre>${JSON.stringify(tokens, null, 2)}</pre>
  `)
})

app.listen(PORT, () => {
  console.log(`Client app running on http://localhost:${PORT}`)
  console.log(`Visit http://localhost:${PORT} to start the GitHub OAuth flow`)
})
