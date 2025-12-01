# Deploy Burr in Vercel

[Vercel](https://vercel.com/) - serverless platform for frontend frameworks and serverless functions.

Here we have an example of how to deploy a Burr application as a Vercel Serverless Function.

## Prerequisites

- **Node.js**: Required for Vercel CLI (v14 or higher)
- **Vercel Account**: Sign up at [vercel.com](https://vercel.com/signup) (free tier available)

## Step-by-Step Guide

### 1. Install Vercel CLI:

```bash
npm install -g vercel
```

### 2. Local tests:

Start the local development server:

```bash
vercel dev
```

Send test request to check if the function executes correctly:

```bash
curl -X POST "http://localhost:3000/api/counter" \
  -H "Content-Type: application/json" \
  -d '{"number": 5}'
```

Expected response:

```json
{"counter": 5, "counter_limit": 5, "__SEQUENCE_ID": 5, "__PRIOR_STEP": "result"}
```

### 3. Login to Vercel:

```bash
vercel login
```

This will open your browser to authenticate with your Vercel account.

### 4. Deploy to Vercel (Preview):

Deploy to a preview environment for testing:

```bash
vercel
```

### 5. Test Preview Deployment:

Vercel will provide a preview URL. Test it:

```bash
curl -X POST "https://your-project-xxx.vercel.app/api/counter" \
  -H "Content-Type: application/json" \
  -d '{"number": 5}'
```

### 6. Deploy to Production:

Once preview testing is successful, deploy to production:

```bash
vercel --prod
```

Your production URL will be:

```
https://your-project.vercel.app
```

### 7. Test Production Deployment:

```bash
curl -X POST "https://your-project.vercel.app/api/counter" \
  -H "Content-Type: application/json" \
  -d '{"number": 5}'
```

## Alternative: Deploy via Git Integration (Recommended)

### Import project in Vercel Dashboard:

- Go to https://vercel.com/new
- Click "Import Git Repository"
- Select your repository
- Click "Deploy"

## Troubleshooting

### If deployment fails:

View detailed logs:

```bash
vercel logs --follow
```

### If function returns 404:

Ensure your handler file is in the `api/` directory with correct format.

### If you see deployment URL instead of production URL:

The production URL is always in the format: `https://your-project.vercel.app`

Check your Vercel Dashboard → Domains section for the correct URL.

## Resources

- [Vercel Documentation](https://vercel.com/docs)
- [Vercel Python Runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel CLI Reference](https://vercel.com/docs/cli)