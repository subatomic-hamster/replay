# Replay Court: the Alexa skill package

A custom skill in the Development stage, in ASK CLI layout:

- `skill-package/skill.json`: the manifest (en-US, HTTPS endpoint with a wildcard
  certificate on the API's Function URL + `/alexa`)
- `skill-package/interactionModels/custom/en-US.json`: the interaction model (invocation
  `replay court`; `PairIntent`, `ExportReelIntent`, `ClipThatIntent` and the built-ins)

The backend is `POST /alexa` in services/api (`replay_api/alexa_routes.py`). The runbook,
the simulator test and the TV contract are in docs/alexa.md.

## Console steps

Sign in with the Amazon account the Fire TV is registered to.

1. https://developer.amazon.com/alexa/console/ask > **Create Skill**. Name `Replay Court`,
   locale **English (US)** (it must match the Fire TV's language), type **Custom**,
   hosting **Provision your own**, template **Start from Scratch**.
2. **Build > Interaction Model > JSON Editor**: paste
   `skill-package/interactionModels/custom/en-US.json`, then **Save** and **Build skill**.
3. **Build > Endpoint > HTTPS**. Default Region:
   `https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws/alexa`. Certificate:
   **"My development endpoint is a sub-domain of a domain that has a wildcard certificate
   from a certificate authority"**. **Save**.
4. Copy the Skill ID and put it in SSM (no redeploy needed):

   ```sh
   aws ssm put-parameter --profile replay --region us-east-1 \
     --name /replay/alexa-skill-id --type String --value 'amzn1.ask.skill.PASTE-YOURS'
   ```

5. **Test** tab: set "Skill testing is enabled in" to **Development**. Type
   `open replay court`. Expect "Your TV isn't paired yet. ..."

The ASK CLI (`ask deploy`) can use the same `skill-package/`, but for one skill the
console is quicker and needs no vendor id.
