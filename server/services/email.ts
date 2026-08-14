import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);

const APP_URL = process.env.APP_URL
  || (process.env.REPLIT_DEPLOYMENT_URL ? `https://${process.env.REPLIT_DEPLOYMENT_URL}` : null)
  || "https://xiomara.ai";

export async function sendTeamInviteEmail(params: {
  toEmail: string;
  inviterName: string;
  clientNames: string[];
  shareToken: string;
}) {
  const { toEmail, inviterName, clientNames, shareToken } = params;
  const clientList = clientNames.join(", ");
  const accessUrl = `${APP_URL}/api/shared/${shareToken}`;

  try {
    const { data, error } = await resend.emails.send({
      from: "Xiomara <noreply@xiomara.ai>",
      to: toEmail,
      subject: `${inviterName} te ha invitado a Xiomara`,
      html: `
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; background: #0f1729; color: #e2e8f0; border-radius: 12px; overflow: hidden;">
          <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0f1729 100%); padding: 40px 32px; text-align: center;">
            <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: #f59e0b;">Xiomara</h1>
            <p style="margin: 8px 0 0; font-size: 14px; color: #94a3b8;">Marketing Intelligence Platform</p>
          </div>
          <div style="padding: 32px;">
            <h2 style="margin: 0 0 16px; font-size: 20px; color: #f1f5f9;">Has sido invitado/a a colaborar</h2>
            <p style="margin: 0 0 24px; font-size: 15px; line-height: 1.6; color: #cbd5e1;">
              <strong style="color: #f59e0b;">${inviterName}</strong> te ha invitado a acceder a la plataforma Xiomara para los siguientes clientes:
            </p>
            <div style="background: #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
              <p style="margin: 0; font-size: 14px; color: #f59e0b; font-weight: 600;">${clientList}</p>
            </div>
            <p style="margin: 0 0 24px; font-size: 15px; line-height: 1.6; color: #cbd5e1;">
              Haz clic en el boton de abajo para acceder directamente a la plataforma. No necesitas crear una cuenta.
            </p>
            <div style="text-align: center; margin: 32px 0;">
              <a href="${accessUrl}" style="display: inline-block; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #0f1729; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-size: 16px; font-weight: 600;">
                Acceder a Xiomara
              </a>
            </div>
            <p style="margin: 0; font-size: 13px; color: #64748b; text-align: center;">
              Este enlace es personal. No lo compartas con otras personas.
            </p>
          </div>
          <div style="padding: 24px 32px; background: #0b1120; text-align: center;">
            <p style="margin: 0; font-size: 12px; color: #475569;">&copy; 2026 Xiomara. Todos los derechos reservados.</p>
          </div>
        </div>
      `,
    });

    if (error) {
      console.error("Resend error sending invite email:", error);
      return { success: false, error: error.message };
    }

    console.log(`Invite email sent to ${toEmail}, id: ${data?.id}`);
    return { success: true, emailId: data?.id };
  } catch (err) {
    console.error("Failed to send invite email:", err);
    return { success: false, error: String(err) };
  }
}
