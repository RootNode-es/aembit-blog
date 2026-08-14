const http = require("http");
const { URL } = require("url");
const { execFile } = require("child_process");

const PORT = 8080;
const AWS_REGION = "us-east-1";
const USER_ID = "ec2-test-user";

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (url.pathname !== "/oauth/callback") {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found");
    return;
  }

  console.log("\n========================================");
  console.log("AgentCore OAuth callback received");
  console.log("========================================");

  console.log("Query parameters:");

  for (const [key, value] of url.searchParams.entries()) {
    console.log(`  ${key}: ${value}`);
  }

  const sessionUri = url.searchParams.get("session_id");
  const error = url.searchParams.get("error");

  if (error) {
    console.error(`OAuth error: ${error}`);

    res.writeHead(400, {
      "Content-Type": "text/html",
    });

    res.end(`
      <html>
        <body>
          <h1>Authorization failed</h1>
          <p>${error}</p>
        </body>
      </html>
    `);

    return;
  }

  if (!sessionUri) {
    console.error("No session_id received");

    res.writeHead(400, {
      "Content-Type": "text/html",
    });

    res.end(`
      <html>
        <body>
          <h1>Authorization failed</h1>
          <p>No session_id was provided.</p>
        </body>
      </html>
    `);

    return;
  }

  console.log("\nSession ID received.");
  console.log("Completing AgentCore OAuth session...");

  try {
    /*
     * We deliberately use the AWS CLI here rather than putting AWS
     * credentials in this Node process.
     *
     * The EC2/application that initiated the flow must have permission
     * to call CompleteResourceTokenAuth.
     */
    await runAwsCli([
      "bedrock-agentcore",
      "complete-resource-token-auth",
      "--region",
      AWS_REGION,
      "--session-uri",
      sessionUri,
      "--user-identifier",
      JSON.stringify({
        userId: USER_ID,
      }),
    ]);

    console.log("OAuth session successfully completed.");

    res.writeHead(200, {
      "Content-Type": "text/html",
    });

    res.end(`
      <!DOCTYPE html>
      <html>
        <head>
          <title>GitHub Authorization Complete</title>
        </head>
        <body>
          <h1>Authorization successful</h1>
          <p>
            AgentCore has completed the OAuth session.
          </p>
          <p>
            You can close this window.
          </p>
        </body>
      </html>
    `);

  } catch (err) {
    console.error("\nFailed to complete OAuth session:");
    console.error(err.message);

    res.writeHead(500, {
      "Content-Type": "text/html",
    });

    res.end(`
      <!DOCTYPE html>
      <html>
        <body>
          <h1>Authorization failed</h1>
          <p>Could not complete the AgentCore OAuth session.</p>
        </body>
      </html>
    `);
  }
});


function runAwsCli(args) {
  return new Promise((resolve, reject) => {

    execFile(
      "aws",
      args,
      {
        maxBuffer: 1024 * 1024,
      },
      (error, stdout, stderr) => {

        if (stdout) {
          console.log(stdout);
        }

        if (stderr) {
          console.error(stderr);
        }

        if (error) {
          reject(error);
        } else {
          resolve(stdout);
        }
      }
    );
  });
}


server.listen(PORT, "localhost", () => {
  console.log("========================================");
  console.log("AgentCore OAuth Callback Server");
  console.log("========================================");
  console.log(`Listening on http://localhost:${PORT}`);
  console.log(
    `Callback URL: http://localhost:${PORT}/oauth/callback`
  );
  console.log("\nWaiting for AgentCore OAuth callback...\n");
});
