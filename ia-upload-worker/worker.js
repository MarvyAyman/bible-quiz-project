/**
 * ia-upload-worker
 * -----------------
 * وسيط بسيط شغال على Cloudflare Workers، مهمته الوحيدة إنه ياخد ملف من متصفح
 * المستخدم ويعمله "Stream" مباشرة لـ Archive.org (S3-like API) من غير ما يخزّن
 * الملف كامل في الميموري، ومن غير ما يفضح مفاتيح Archive.org للمتصفح.
 *
 * ليه ده أفضل من الرفع المباشر من المتصفح لـ archive.org؟
 * 1) Archive.org مبيسمحش بطلبات CORS من أي دومين خارجي، فالرفع المباشر من
 *    المتصفح بيتعمله رفض (403) - ده اللي حصل معاكِ.
 * 2) لو رجّعنا الرفع يعدي على Django/Vercel هيبقى محدود بحجم الـ request
 *    (~4.5MB على الـ Hobby tier) ومدة تنفيذ الـ function القصيرة.
 * 3) الـ Worker ده مش عنده الحدين دول، وبيعمل streaming حقيقي للملف.
 *
 * طريقة الاستخدام من المتصفح:
 *   PUT https://<your-worker>.workers.dev/upload/{identifier}/{filename}
 *   Headers: x-archive-meta-title, x-archive-meta-mediatype, x-archive-meta-collection,
 *            x-archive-meta-language, x-archive-meta-subject, x-archive-interactive-priority
 *   Body: الملف نفسه (raw bytes)
 *
 * الـ Worker هو اللي بيضيف الـ Authorization header (المفتاح السري) قبل ما
 * يبعت الطلب لـ Archive.org - المفتاح مش موجود في كود المتصفح خالص.
 */

export default {
  async fetch(request, env) {
    // دومين تطبيقك بالظبط (من غير / في الآخر). لازم يتظبط في wrangler.toml أو Dashboard
    const ALLOWED_ORIGIN = env.ALLOWED_ORIGIN || "http://localhost:8000";
    const origin = request.headers.get("Origin") || "";
    const originAllowed = origin === ALLOWED_ORIGIN;

    const corsHeaders = {
      "Access-Control-Allow-Origin": originAllowed ? origin : "null",
      "Access-Control-Allow-Methods": "PUT, OPTIONS",
      "Access-Control-Allow-Headers":
        "Content-Type, x-archive-meta-title, x-archive-meta-mediatype, x-archive-meta-collection, " +
        "x-archive-meta-language, x-archive-meta-subject, x-archive-interactive-priority",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin",
    };

    // طلب الـ Preflight اللي المتصفح بيبعته أول أي PUT فيه headers مخصصة
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    if (!originAllowed) {
      return new Response("Forbidden origin", { status: 403, headers: corsHeaders });
    }

    if (request.method !== "PUT") {
      return new Response("Method not allowed", { status: 405, headers: corsHeaders });
    }

    // متوقعين شكل المسار: /upload/{identifier}/{filename}
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length !== 3 || parts[0] !== "upload") {
      return new Response("Bad path, expected /upload/{identifier}/{filename}", {
        status: 400,
        headers: corsHeaders,
      });
    }
    const [, identifier, filename] = parts;

    // تحقق بسيط من شكل الـ identifier عشان محدش يستخدم الـ Worker كوسيط
    // عشوائي لأي مكان تاني غير Archive.org
    if (!/^[a-z0-9-]{5,100}$/.test(identifier)) {
      return new Response("Bad identifier format", { status: 400, headers: corsHeaders });
    }
    if (!/^[a-zA-Z0-9._-]{1,150}$/.test(filename)) {
      return new Response("Bad filename format", { status: 400, headers: corsHeaders });
    }

    // (اختياري لكن مفيد) حد أقصى معقول لحجم الملف، عدّليه براحتك
    const MAX_BYTES = 500 * 1024 * 1024; // 500MB
    const contentLength = Number(request.headers.get("Content-Length") || 0);
    if (contentLength && contentLength > MAX_BYTES) {
      return new Response("File too large", { status: 413, headers: corsHeaders });
    }

    const targetUrl = `https://s3.us.archive.org/${identifier}/${encodeURIComponent(filename)}`;

    // بنمرر بس الـ headers الخاصة بالـ metadata اللي المتصفح بعتها، وبنحط
    // الـ Authorization إحنا من الـ secrets المخزنة في الـ Worker (مش من المتصفح)
    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
      const k = key.toLowerCase();
      if (k.startsWith("x-archive-meta") || k === "x-archive-interactive-priority" || k === "content-type") {
        forwardHeaders.set(key, value);
      }
    }
    forwardHeaders.set("x-amz-auto-make-bucket", "1");
    forwardHeaders.set("Authorization", `LOW ${env.IA_ACCESS_KEY}:${env.IA_SECRET_KEY}`);

    let iaResponse;
    try {
      iaResponse = await fetch(targetUrl, {
        method: "PUT",
        headers: forwardHeaders,
        body: request.body, // ✅ streaming حقيقي - مش بيتحمل كامل في ميموري الـ Worker
        duplex: "half", // مطلوب من Cloudflare Workers لما الـ body بيكون Stream
      });
    } catch (err) {
      return new Response("Upstream error contacting Archive.org: " + err.message, {
        status: 502,
        headers: corsHeaders,
      });
    }

    const downloadUrl = `https://archive.org/download/${identifier}/${encodeURIComponent(filename)}`;
    const respHeaders = new Headers(corsHeaders);
    respHeaders.set("Content-Type", "application/json; charset=utf-8");

    return new Response(
      JSON.stringify({
        ok: iaResponse.ok,
        status: iaResponse.status,
        download_url: downloadUrl,
      }),
      { status: iaResponse.status, headers: respHeaders }
    );
  },
};