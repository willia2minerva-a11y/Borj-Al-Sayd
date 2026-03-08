document.addEventListener('DOMContentLoaded', () => {
    
    // تشغيل زر القائمة العلوية
    const menuBtn = document.getElementById('menu-toggle');
    const sideNav = document.getElementById('side-nav');
    if (menuBtn && sideNav) {
        menuBtn.addEventListener('click', () => {
            sideNav.classList.toggle('active');
        });
    }

    // نظام الطي
    document.querySelectorAll('.accordion-header').forEach(acc => {
        acc.addEventListener('click', function() {
            const content = this.nextElementSibling;
            if (content.style.maxHeight) {
                content.style.maxHeight = null;
            } else {
                content.style.maxHeight = content.scrollHeight + "px";
            }
        });
    });

    // لغز الكلمات المتسلسلة
    let currentSequence = 1;
    const secretWords = document.querySelectorAll('.secret-word');
    const totalWords = secretWords.length;
    
    secretWords.forEach(word => {
        word.addEventListener('click', function() {
            const order = parseInt(this.getAttribute('data-order'));
            if (order === currentSequence) {
                this.classList.add('glow-effect');
                currentSequence++;
                if (currentSequence > totalWords && totalWords > 0) {
                    alert('🎉 تسلسل صحيح! التقط صورة للشاشة وأرسلها للإدارة لأخذ النقاط.');
                    currentSequence = 1;
                }
            } else {
                currentSequence = 1;
                secretWords.forEach(w => w.classList.remove('glow-effect'));
            }
        });
    });

    // تحذير تغيير الاسم
    const nameChangeForm = document.getElementById('name-change-form');
    if (nameChangeForm) {
        nameChangeForm.addEventListener('submit', function(e) {
            const confirmChange = confirm('تنبيه هام ⚠️\nإذا قمت بتغيير اسمك الآن، فلن تتمكن من تغييره مرة أخرى إلا بعد مرور 15 يوماً. هل أنت متأكد؟');
            if (!confirmChange) {
                e.preventDefault();
            }
        });
    }
});
