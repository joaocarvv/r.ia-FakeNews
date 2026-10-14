import { initializeApp } from 'firebase/app'
import { getFirestore } from 'firebase/firestore'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, createUserWithEmailAndPassword, signInWithEmailAndPassword, sendPasswordResetEmail, updateProfile } from 'firebase/auth'

const app = initializeApp({
  apiKey: 'AIzaSyBNhUUthVUIxMwVdAI_wuXIn4ozu1be99g',
  authDomain: 'ria-fakenews.firebaseapp.com',
  projectId: 'ria-fakenews',
  storageBucket: 'ria-fakenews.firebasestorage.app',
  messagingSenderId: '474105993147',
  appId: '1:474105993147:web:0af99aa3b9858e5b64969e',
})
export const auth = getAuth(app)
export const db = getFirestore(app)
const provider = new GoogleAuthProvider()
provider.setCustomParameters({ prompt: 'select_account' })
export const loginWithGoogle = () => signInWithPopup(auth, provider)
export const logout = () => signOut(auth)
export const loginWithEmail = (email: string, password: string) => signInWithEmailAndPassword(auth, email.trim(), password)
export async function registerWithEmail(name: string, email: string, password: string) {
  const created = await createUserWithEmailAndPassword(auth, email.trim(), password)
  await updateProfile(created.user, { displayName: name.trim() })
  return created
}
export const requestPasswordReset = (email: string) => sendPasswordResetEmail(auth, email.trim())
export function authErrorMessage(error: unknown): string {
  const code = (error as { code?: string })?.code
  const messages: Record<string, string> = {
    'auth/popup-closed-by-user': 'Você fechou a janela de login. Clique novamente para entrar.',
    'auth/cancelled-popup-request': 'Já existe uma tentativa de login em andamento.',
    'auth/popup-blocked': 'Permita pop-ups para este site e tente novamente.',
    'auth/unauthorized-domain': 'Este domínio precisa ser autorizado no Firebase Authentication.',
    'auth/operation-not-allowed': 'Ative o provedor Google no Firebase Authentication.',
    'auth/configuration-not-found': 'Configure o Firebase Authentication e ative o provedor Google.',
    'auth/network-request-failed': 'Não foi possível conectar ao Firebase. Confira sua conexão.',
    'auth/invalid-api-key': 'A configuração do Firebase não foi aceita. Confira a chave do projeto.',
    'auth/user-disabled': 'Esta conta está desativada. Entre em contato com o administrador.',
    'auth/email-already-in-use': 'Este e-mail já está cadastrado. Entre com sua senha ou recupere o acesso.',
    'auth/invalid-email': 'Digite um endereço de e-mail válido.',
    'auth/weak-password': 'A senha não atende aos requisitos do Firebase. Escolha uma senha mais forte.',
    'auth/invalid-credential': 'E-mail ou senha inválidos.',
    'auth/wrong-password': 'E-mail ou senha inválidos.',
    'auth/user-not-found': 'E-mail ou senha inválidos.',
    'auth/too-many-requests': 'Muitas tentativas. Aguarde um pouco antes de tentar novamente.',
  }
  return messages[code || ''] || 'Não foi possível entrar. Tente novamente e confira a configuração do Firebase.'
}
