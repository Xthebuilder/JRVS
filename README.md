This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

### Prerequisites

- Node.js 18+ installed
- Firebase account ([Sign up here](https://firebase.google.com/))

### Firebase Setup

**📖 For detailed setup instructions, see [FIREBASE_SETUP.md](./FIREBASE_SETUP.md).**

#### Quick Setup

1. **Create a Firebase Project**
   - Go to [Firebase Console](https://console.firebase.google.com/)
   - Click "Add project" and follow the setup wizard
   - Enable the following services:
     - **Authentication**: Enable Email/Password and Google sign-in methods
     - **Firestore Database**: Create a database in production mode (or test mode for development)
     - **Storage**: Enable Firebase Storage (optional, for file uploads)

2. **Get Firebase Configuration**
   - In Firebase Console, go to Project Settings (gear icon)
   - Scroll down to "Your apps" section
   - Click the web icon (`</>`) to add a web app
   - Register your app with a nickname
   - Copy the Firebase configuration object

3. **Create Environment Variables File**
   - Create a `.env.local` file in the root directory
   - Add the following environment variables with your Firebase credentials:

```env
NEXT_PUBLIC_FIREBASE_API_KEY=your-api-key-here
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your-project-id
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=your-messaging-sender-id
NEXT_PUBLIC_FIREBASE_APP_ID=your-app-id
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=your-measurement-id
```

4. **Configure Firestore Security Rules** (for development)
   - Go to Firestore Database > Rules
   - For development, you can use:
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /{document=**} {
         allow read, write: if request.auth != null;
       }
     }
   }
   ```
   - ⚠️ **Important**: Update these rules for production to match your security requirements

For detailed steps, troubleshooting, and security rules configuration, please see [FIREBASE_SETUP.md](./FIREBASE_SETUP.md).

### Install Dependencies

```bash
npm install
# or
yarn install
# or
pnpm install
```

### Run the Development Server

```bash   
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
