'use strict';
import gulp from 'gulp';
import javascriptObfuscator from 'gulp-javascript-obfuscator';

gulp.task('uglify', () => {
    return gulp.src(['src/**/*.js', '!src/**/*.test.js'])
        .pipe(javascriptObfuscator({
            compact: true,
            renameGlobals: true,
            unicodeEscapeSequence: true,
            splitStrings: true,
            selfDefending: true,
            controlFlowFlattening: true,
            controlFlowFlatteningThreshold: 0.75,
            deadCodeInjection: true,
            deadCodeInjectionThreshold: 0.4
        }))
        .pipe(gulp.dest('./dist'));
});


gulp.task('default', gulp.series(['uglify']));