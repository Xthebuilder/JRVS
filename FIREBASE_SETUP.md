# Firebase セットアップガイド

このガイドでは、JRVS プロジェクトで Firebase をセットアップする手順を説明します。

## 📋 セットアップ手順

### 1. Firebase プロジェクトの作成

1. [Firebase Console](https://console.firebase.google.com/) にアクセス
2. 「プロジェクトを追加」をクリック
3. プロジェクト名を入力（例: `jrvs-scheduler`）
4. Google Analytics の設定（オプション）
5. 「プロジェクトを作成」をクリック

### 2. Firebase サービスの有効化

#### Authentication（認証）

1. Firebase Console で「Authentication」を選択
2. 「始める」をクリック
3. 「Sign-in method」タブで以下を有効化：
   - **Email/Password**: 有効化
   - **Google**: 有効化（プロジェクトのサポートメールを設定）

#### Firestore Database（データベース）

1. 「Firestore Database」を選択
2. 「データベースを作成」をクリック
3. セキュリティルールの選択：
   - **開発環境**: 「テストモードで開始」を選択
   - **本番環境**: 「本番モードで開始」を選択（後でルールを設定）
4. ロケーションを選択（例: `asia-northeast1` - Tokyo）
5. 「有効にする」をクリック

#### Storage（ストレージ）- オプション

1. 「Storage」を選択
2. 「始める」をクリック
3. セキュリティルールを設定（開発環境ではテストモードでも可）
4. ロケーションを選択
5. 「完了」をクリック

### 3. Web アプリの登録

1. Firebase Console で「プロジェクトの設定」（⚙️アイコン）をクリック
2. 「マイアプリ」セクションまでスクロール
3. Web アイコン（`</>`）をクリック
4. アプリのニックネームを入力（例: `JRVS Web App`）
5. 「Firebase Hosting も設定する」はチェックしない（任意）
6. 「アプリを登録」をクリック
7. **Firebase 構成オブジェクトをコピー**

### 4. 環境変数の設定

1. プロジェクトのルートディレクトリに `.env.local` ファイルを作成

2. 以下の内容を追加（Firebase Console からコピーした値を入力）：

```env
NEXT_PUBLIC_FIREBASE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your-project-id
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=123456789012
NEXT_PUBLIC_FIREBASE_APP_ID=1:123456789012:web:abcdef1234567890
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=G-XXXXXXXXXX
```

3. 実際の Firebase 構成値に置き換えてください

### 5. Firestore セキュリティルールの設定

#### 開発環境用ルール

Firestore Database > Rules で以下を設定：

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // 認証済みユーザーのみアクセス可能
    match /{document=**} {
      allow read, write: if request.auth != null;
    }
    
    // ユーザー固有のデータ
    match /users/{userId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
    
    // メッセージ
    match /messages/{messageId} {
      allow read, write: if request.auth != null;
    }
    
    // カレンダー
    match /calendars/{calendarId} {
      allow read, write: if request.auth != null;
    }
    
    // イベント
    match /events/{eventId} {
      allow read, write: if request.auth != null;
    }
  }
}
```

⚠️ **注意**: 本番環境では、より厳密なセキュリティルールを設定してください。

### 6. 動作確認

1. 開発サーバーを起動：
   ```bash
   npm run dev
   ```

2. ブラウザのコンソールを開く（F12）
3. Firebase の初期化メッセージを確認：
   - ✅ `Firebase configuration loaded successfully` が表示されれば成功
   - ⚠️ 警告が表示される場合は、環境変数を確認してください

## 🔍 トラブルシューティング

### 環境変数が読み込まれない

- `.env.local` ファイルがプロジェクトルートにあるか確認
- ファイル名が正確か確認（`.env.local`）
- 開発サーバーを再起動
- `NEXT_PUBLIC_` プレフィックスが正しく設定されているか確認

### Firebase 初期化エラー

- 環境変数の値が正しいか確認
- Firebase Console でプロジェクトが正しく作成されているか確認
- ブラウザのコンソールでエラーメッセージを確認

### 認証エラー

- Firebase Console で Authentication が有効になっているか確認
- Sign-in method が有効になっているか確認
- 認証ドメインが正しく設定されているか確認

## 📚 参考資料

- [Firebase ドキュメント](https://firebase.google.com/docs)
- [Next.js 環境変数](https://nextjs.org/docs/basic-features/environment-variables)
- [Firebase Authentication](https://firebase.google.com/docs/auth)
- [Cloud Firestore](https://firebase.google.com/docs/firestore)

## ✅ チェックリスト

- [ ] Firebase プロジェクトを作成
- [ ] Authentication を有効化
- [ ] Firestore Database を作成
- [ ] Storage を有効化（オプション）
- [ ] Web アプリを登録
- [ ] `.env.local` ファイルを作成
- [ ] 環境変数を設定
- [ ] Firestore セキュリティルールを設定
- [ ] 開発サーバーで動作確認

## 🚀 次のステップ

Firebase のセットアップが完了したら、以下を実装できます：

1. ユーザー認証機能
2. メッセージ履歴の保存
3. カレンダー情報の保存
4. イベントデータの保存

