// ننتظر حتى يتم تحميل الصفحة بالكامل قبل تشغيل الأكواد
document.addEventListener('DOMContentLoaded', () => {

    // -----------------------------------------
    // 1. زر القائمة الجانبية (Mobile Menu)
    // -----------------------------------------
    const menuBtn = document.getElementById('menu-btn');
    if (menuBtn) {
        menuBtn.addEventListener('click', () => {
            // حالياً سنضع رسالة تنبيه، وسنربطها بالقائمة الجانبية لاحقاً عند تصميمها
            alert('قريباً: فتح قائمة الموقع (الرئيسية، المتجر، المقبرة)');
        });
    }

    // -----------------------------------------
    // 2. نظام طي الأخبار (Accordion) للألغاز
    // -----------------------------------------
    const accordions = document.querySelectorAll('.accordion-header');
    accordions.forEach(acc => {
        acc.addEventListener('click', function() {
            this.classList.toggle('active');
            const content = this.nextElementSibling;
            if (content.style.maxHeight) {
                content.style.maxHeight = null; // طي الخبر
            } else {
                content.style.maxHeight = content.scrollHeight + "px"; // فتح الخبر
            }
        });
    });

    // -----------------------------------------
    // 3. لغز الكلمات المتسلسلة (التوهج والترتيب)
    // -----------------------------------------
    let currentSequence = 1; // العداد يبدأ من الكلمة الأولى
    const secretWords = document.querySelectorAll('.secret-word');
    const totalWords = secretWords.length;

    secretWords.forEach(word => {
        word.addEventListener('click', function() {
            // قراءة ترتيب الكلمة التي ضغط عليها اللاعب
            const wordOrder = parseInt(this.getAttribute('data-order'));

            if (wordOrder === currentSequence) {
                // إجابة صحيحة: إضافة تأثير التوهج للكلمة
                this.classList.add('glow-effect');
                currentSequence++; // الانتقال للكلمة التالية

                // التحقق مما إذا كان اللاعب قد ضغط على كل الكلمات بالترتيب
                if (currentSequence > totalWords && totalWords > 0) {
                    alert('🎉 مذهل أيها الصائد! لقد اكتشفت التسلسل السري!');
                    // ملاحظة للمستقبل: هنا سنضع كود إرسال النقطة لقاعدة البيانات بصمت
                    currentSequence = 1; // إعادة تعيين العداد
                }
            } else {
                // إجابة خاطئة أو ترتيب خاطئ: سحب التوهج والعودة للصفر بصمت
                currentSequence = 1;
                secretWords.forEach(w => w.classList.remove('glow-effect'));
            }
        });
    });

});
