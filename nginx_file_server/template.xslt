<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
    <xsl:output method="html" encoding="utf-8" indent="yes"/>
    <xsl:template match="/">
        <xsl:text disable-output-escaping='yes'>&lt;!DOCTYPE html&gt;</xsl:text>
        <html>
            <head>
                <title>
                    <xsl:value-of select="$title"/>
                </title>
                <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
                <style>
                    img {
                    display: inline;
                    width: 300px;
                    margin: 2mm;
                    vertical-align: bottom;
                    }
                    @media all and (max-width: 20.4cm) {
                    img {
                    max-width: calc(100% - 4mm);
                    }
                    }
                    body {
                    margin: 0;
                    }
                </style>
            </head>
            <body>
                <a id="gotoparentfolder">
                    <font color='green' style="margin: 10px;">[ Parent directory ]</font>
                </a>
                <hr />
                <ul style="display:inline; list-style-type:none;">
                    <xsl:for-each select="list/directory">
                        <li>
                            <a href="{.}" title="{.}">
                                <font color='green' style="margin: 10px;">[
                                    <xsl:value-of select="."/>]
                                </font>
                            </a>
                        </li>
                    </xsl:for-each>
                </ul>
                <xsl:for-each select="list/file">
                    <!-- <a href="{.}" title="{.}"><xsl:value-of select="." /></a> -->
                    <xsl:choose>
                        <xsl:when
                                test="contains(' 3gp mpg mov mp4 webm mkv avi wmv flv ogv 3GP MPG  MOV MP4 WEBM MKV AVI WMV FLV OGV ', concat(' ', substring-after(., '.'), ' '))">
                            <table style="display:inline;">
                                <tr>
                                    <td>
                                        <a href="{.}" title="{.}">
                                            <img class="videothumb" src="{.}§vthumb" href="{.}"/>
                                        </a>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <a href="{.}" title="{.}">
                                            <span style="border-top-width: 1px;border-top-style: solid;border-left-width: 1px;border-left-style: solid;border-right-width: 1px;border-right-style: solid;border-bottom-width: 1px;border-bottom-style: solid;padding-left: 4px;padding-top: 4px;padding-right: 4px;padding-bottom: 4px; border-color: #e1e1e1;text-decoration: none;margin-right: 10px;">
                                            🎬
                                                <xsl:value-of select="."/>
                                            </span>
                                        </a>
                                        <br/>`
                                    </td>
                                </tr>
                            </table>
                        </xsl:when>
                        <xsl:when
                                test="contains(' jpg gif jpeg png JPG GIF JPEG PNG ', concat(' ', substring-after(., '.'), ' '))">
                            <table style="display:inline;">
                                <tr>
                                    <td>
                                        <a href="{.}" title="{.}">
                                            <!-- <img class="imagethumb" src="{.}/thumb/large" alt="{.}"/> -->
                                            <img class="imagethumb" src="{.}§thumb§small" alt="{.}"/>
                                        </a>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <a href="{.}" title="{.}">
                                            [📸
                                            <xsl:value-of select="."/>]
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </xsl:when>
                        <xsl:otherwise>
                            <table style="display:inline;">
                                <tr>
                                    <td>
                                        <a href="{.}" title="{.}">
                                            <img class="imagethumb" src="{.}" alt="{.}"/>
                                        </a>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <a class="filethumb" href="{.}" title="{.}">
                                            [🗎
                                            <xsl:value-of select="."/>]
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </xsl:otherwise>
                    </xsl:choose>
                </xsl:for-each>
            </body>
            <script>
pf = document.URL.split('/').slice(0, -2).join('/');
document.getElementById('gotoparentfolder').href = pf;

            </script>
        </html>
    </xsl:template>
</xsl:stylesheet>
