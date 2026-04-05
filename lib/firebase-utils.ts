/**
 * Firebase Utility Functions
 * Helper functions for Firebase operations
 */

import { auth, db } from './firebase';
import { 
  User, 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  GoogleAuthProvider,
  signInWithPopup
} from 'firebase/auth';
import { 
  collection, 
  doc, 
  getDoc, 
  setDoc, 
  updateDoc, 
  deleteDoc,
  getDocs,
  query,
  where,
  Timestamp 
} from 'firebase/firestore';

// Authentication helpers
export const authHelpers = {
  /**
   * Sign in with email and password
   */
  signIn: async (email: string, password: string) => {
    try {
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      return { user: userCredential.user, error: null };
    } catch (error: any) {
      return { user: null, error: error.message };
    }
  },

  /**
   * Sign up with email and password
   */
  signUp: async (email: string, password: string) => {
    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      return { user: userCredential.user, error: null };
    } catch (error: any) {
      return { user: null, error: error.message };
    }
  },

  /**
   * Sign in with Google
   */
  signInWithGoogle: async () => {
    try {
      const provider = new GoogleAuthProvider();
      const userCredential = await signInWithPopup(auth, provider);
      return { user: userCredential.user, error: null };
    } catch (error: any) {
      return { user: null, error: error.message };
    }
  },

  /**
   * Sign out
   */
  signOut: async () => {
    try {
      await signOut(auth);
      return { error: null };
    } catch (error: any) {
      return { error: error.message };
    }
  },

  /**
   * Get current user
   */
  getCurrentUser: (): User | null => {
    return auth.currentUser;
  },

  /**
   * Listen to auth state changes
   */
  onAuthStateChange: (callback: (user: User | null) => void) => {
    return onAuthStateChanged(auth, callback);
  }
};

// Firestore helpers
export const firestoreHelpers = {
  /**
   * Create a document
   */
  createDocument: async <T>(
    collectionName: string,
    documentId: string,
    data: T
  ) => {
    try {
      const docRef = doc(db, collectionName, documentId);
      await setDoc(docRef, {
        ...data,
        createdAt: Timestamp.now(),
        updatedAt: Timestamp.now()
      });
      return { success: true, error: null };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Get a document
   */
  getDocument: async <T>(collectionName: string, documentId: string) => {
    try {
      const docRef = doc(db, collectionName, documentId);
      const docSnap = await getDoc(docRef);
      
      if (docSnap.exists()) {
        return { data: docSnap.data() as T, error: null };
      } else {
        return { data: null, error: 'Document not found' };
      }
    } catch (error: any) {
      return { data: null, error: error.message };
    }
  },

  /**
   * Update a document
   */
  updateDocument: async <T>(
    collectionName: string,
    documentId: string,
    data: Partial<T>
  ) => {
    try {
      const docRef = doc(db, collectionName, documentId);
      await updateDoc(docRef, {
        ...data,
        updatedAt: Timestamp.now()
      });
      return { success: true, error: null };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Delete a document
   */
  deleteDocument: async (collectionName: string, documentId: string) => {
    try {
      const docRef = doc(db, collectionName, documentId);
      await deleteDoc(docRef);
      return { success: true, error: null };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Get all documents from a collection
   */
  getDocuments: async <T>(collectionName: string) => {
    try {
      const querySnapshot = await getDocs(collection(db, collectionName));
      const documents = querySnapshot.docs.map(doc => ({
        id: doc.id,
        ...doc.data()
      })) as T[];
      return { data: documents, error: null };
    } catch (error: any) {
      return { data: [], error: error.message };
    }
  },

  /**
   * Query documents with conditions
   */
  queryDocuments: async <T>(
    collectionName: string,
    field: string,
    operator: any,
    value: any
  ) => {
    try {
      const q = query(collection(db, collectionName), where(field, operator, value));
      const querySnapshot = await getDocs(q);
      const documents = querySnapshot.docs.map(doc => ({
        id: doc.id,
        ...doc.data()
      })) as T[];
      return { data: documents, error: null };
    } catch (error: any) {
      return { data: [], error: error.message };
    }
  }
};

// Collection names (for type safety)
export const COLLECTIONS = {
  USERS: 'users',
  MESSAGES: 'messages',
  CALENDARS: 'calendars',
  EVENTS: 'events'
} as const;

