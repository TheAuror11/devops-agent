# Runbooks and RAG

Place Markdown playbooks in `/runbooks`. They are chunked and indexed at seed / `POST /v1/runbooks`.

The investigation tool `retrieve_runbooks` is how the model grounds remediations. Skills (`POST /v1/agent-spaces/{id}/skills`) are the *procedure* (when to call which MCP tool); runbooks are the *facts*.

Seeded corpus:

- DynamoDB throttling / connection pool  
- Lambda errors  
- ALB 5xx  
- ECS crash loop  
- RDS CPU / connections  
- Deployment correlation  

Authoring tips (aligned with AWS DevOps Agent skills guidance):

- Lead with **signals**, then **parallel hypotheses**, then **operator-executed mitigation**, then **validation / rollback / prevention**.  
- Name SHAs, metric namespaces, and log groups that exist in the Agent Space.  
- Never instruct the agent to run mutating AWS APIs.
